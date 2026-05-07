#!/usr/bin/env nix-shell
#! nix-shell -i bash --packages bash jq

set -o errexit
set -o pipefail
set -o nounset

#####################################################################
################## CONSTANTS ########################################
#####################################################################

# primary orthanc
source_orthanc_url="${SOURCE_ORTHANC_URL:-https://local.pacs.ocb.msf.org/}"
dest_orthanc_url="${DEST_ORTHANC_URL:-https://local.pacs.archive.ocb.msf.org/}"
username=""
password=""

# destination orthanc
dest_username="${DEST_USERNAME:-}"
dest_password="${DEST_PASSWORD:-}"
api_key="${API_KEY:-}"


rate_limit="${RATE_LIMIT:-50}"
log_file="${LOG_FILE:-orthanc_migration.log}"
retry_limit="${RETRY_LIMIT:-3}"
quarantine_file="${QUARANTINE_FILE:-quarantine.txt}"
since=0

# normalize URLs (avoid double slash issues)
source_orthanc_url="${source_orthanc_url%/}/"
dest_orthanc_url="${dest_orthanc_url%/}/"

#####################################################################
################## FUNCTIONS ########################################
#####################################################################

# log function to write log messages
log() {
    local level="$1"
    local msg="$2"
    echo "$(date '+%Y-%m-%d %H:%M:%S %Z') [$level] $msg" | tee -a "$log_file"
}

cutoff_date="$(date -d "2 years ago" +"%Y%m%d")"
log "INFO" "Cutoff date: $cutoff_date"

# check if a study_id is quarantined
is_quarantined() {
    local study_id="$1"
    grep -Fxq "$study_id" "$quarantine_file" 2>/dev/null
}

# add study_id to quarantine file
add_to_quarantine() {
    local study_id="$1"

    # quicly check the study_id is not already existing before writing
    if ! grep -Fxq "$study_id" "$quarantine_file" 2>/dev/null; then
        echo "$study_id" >> "$quarantine_file"
        ((rate_limit++))
        log "INFO" "Added $study_id to quarantine and increased limit to $rate_limit"
    else
        log "INFO" "$study_id already in quarantine"
    fi
}

# function to query studies older than cutoff date, in batches of 50
find_old_studies() {
    curl -sS -H "api-key: or7ANqt2NEoxXLVD" "https://local.pacs.ocb.msf.org/studies?expand&since=$since&limit=$rate_limit" \
    | jq --arg cutoff "$cutoff_date" '
        .[]
        | select(
            .MainDicomTags.StudyDate != null and
            .MainDicomTags.StudyDate <= $cutoff
        )
        | .ID
    '
}

# quickly check if the destination server is reachable
check_destination() {
    curl -sS -f -u "$dest_username:$dest_password" \
        -H "api-key: $api_key" \
        "${dest_orthanc_url}system" >/dev/null
    return
}

# transfer studies from primary to destination server
transfer_study() {
    local study_id="$1"

    # sanitize study_id (fix malformed URL issue)
    study_id="$(echo "$study_id" | tr -d '\r\n[:space:]')"

    if [[ -z "$study_id" ]]; then
        log "ERROR" "Empty study_id detected, skipping"
        return
    fi

    log "DEBUG" "Processing study_id: [$study_id]"

    if is_quarantined "$study_id"; then
        log "INFO" "Skipping quarantined study $study_id"
        return
    fi

    log "INFO" "Transferring study $study_id"

    for ((attempt=1; attempt<=retry_limit; attempt++)); do

        tmpdir="$(mktemp -d /tmp/orthanc_${study_id}.XXXXXX)"
        tmpfile="$tmpdir/archive.zip"

        # first download
        http_code=$(curl -sS -w "%{http_code}" \
            -f \
            -H "api-key: $api_key" \
            "${source_orthanc_url}studies/${study_id}/archive" \
            -o "$tmpfile" || echo "000")

        if [[ "$http_code" != "200" ]]; then
            log "ERROR" "Download failed for $study_id (attempt $attempt) HTTP=$http_code"
            rm -rf "$tmpdir"
            sleep 2
            continue
        fi

        if [[ ! -s "$tmpfile" ]]; then
            log "ERROR" "Downloaded file is empty for $study_id"
            rm -rf "$tmpdir"
            sleep 2
            continue
        fi

        # then upload
        response="$(curl -sS -w "\n%{http_code}" \
            -f \
            -X POST "${dest_orthanc_url}instances" \
            -H "Content-Type: application/zip" \
            -H "api-key: $api_key" \
            --data-binary @"$tmpfile" || true)"

        log "INFO" "Response when trying to upload is: $response"

        http_code="$(echo "$response" | tail -n1)"
        body="$(echo "$response" | sed '$d')"

        rm -rf "$tmpdir"

        if [[ "$http_code" != "200" && "$http_code" != "204" ]]; then
            log "ERROR" "Upload failed for $study_id (attempt $attempt) HTTP=$http_code"
            sleep 2
            continue
        fi

        log "INFO" "Response: $body"

        status="$(echo "$body" | jq -r '.. | .Status? // empty' | head -n1)"

        if [[ -z "$status" ]]; then
            log "ERROR" "Invalid response for $study_id"
            sleep 2
            continue
        fi

        case "$status" in
            Success)
                log "INFO" "Upload successful for $study_id"
                delete_study "$study_id"
                return
                ;;
            AlreadyStored)
                log "INFO" "$study_id already stored"
                add_to_quarantine "$study_id"
                return
                ;;
            FilteredOut)
                log "INFO" "Study $study_id filtered out"
                return
                ;;
            Failure)
                log "ERROR" "Upload failure for $study_id (attempt $attempt)"
                ;;
            *)
                log "ERROR" "Unexpected status '$status' for $study_id"
                ;;
        esac

        sleep 2
    done

    log "ERROR" "Study $study_id failed after $retry_limit attempts"
    add_to_quarantine "$study_id"
}

delete_study() {
    local study_id="$1"

    log "INFO" "Deleting study $study_id from source"

    if curl -sS -f \
        -H "api-key: $api_key" \
        -X DELETE "${source_orthanc_url}studies/${study_id}" >/dev/null; then
        log "INFO" "Study $study_id deleted"
    else
        log "ERROR" "Failed to delete study $study_id"
    fi
}

if ! check_destination; then
    log "ERROR" "Destination server not reachable"
    exit 1
fi

#####################################################################
################## MAIN FUNCTION  ###################################
#####################################################################

while true; do
    log "INFO" "Querying for studies older than $cutoff_date..."

    response="$(find_old_studies || true)"

    log "INFO" "$response"

    if [[ -z "$response" ]]; then
        log "ERROR" "Failed to query studies, checking another page"
        since=$((since + 50))
        continue
    fi

    # if ! echo "$response" | jq empty >/dev/null 2>&1; then
    #     log "ERROR" "Invalid JSON response"
    #     break
    # fi

    study_ids="$(echo "$response" | jq -r )"

    log "DEBUG" "study_ids=[${study_ids}]"

    if [[ -z "$study_ids" ]]; then
        log "INFO" "No more studies to process."
        break
    fi

    processed_any=false

    while IFS= read -r study_id; do
        study_id="$(echo "$study_id" | tr -d '\r\n[:space:]')"
        [[ -z "$study_id" ]] && continue

        if is_quarantined "$study_id"; then
            continue
        fi

        processed_any=true
        transfer_study "$study_id"

    done <<< "$study_ids"

    if [[ "$processed_any" = false ]]; then
        log "INFO" "All studies are quarantined. Stopping."
        break
    fi

    since=$((since + 50))
    log "INFO" "Batch complete... at page $since"
    sleep 2
done

log "INFO" "Migration finished."
