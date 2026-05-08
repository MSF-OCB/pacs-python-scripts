import json
import os
from urllib import response
import requests
from datetime import datetime, timedelta
import pandas as pd
import time
from add_TEI_DI import add_TEI_DI
from dotenv import load_dotenv
import tempfile, shutil

load_dotenv()
API_KEY = os.getenv("API_KEY")
ORTHANC_URL = os.getenv("ORTHANC_URL")
API_USERNAME = os.getenv("API_USERNAME")
API_PASSWORD = os.getenv("API_PASSWORD")
API_USER = (API_USERNAME, API_PASSWORD)
EXCEL_FILE = "dose_data.xlsx"
LOG_FILE_SUCCESS = "succesfull_instances.log"
LOG_FILE_QUARANTINE = "quarantined_instances.log"
BATCH_SIZE = 5


# Define functions to interact with Orthanc API, process the data, and manage logs and Excel file
def get_existing_instance_ids(log_path_success: str, log_path_quarantine: str) -> set:
    """Read two log files and return a set of already-processed instance IDs."""
    existing_ids = set()
    
    for path in (log_path_success, log_path_quarantine):
        if os.path.exists(path):
            with open(path, "r") as f:
                existing_ids.update(line.strip() for line in f if line.strip())
    
    return existing_ids
   
def get_all_instances(since=0, limit=50, max_retries=2):
    url = f"{ORTHANC_URL}/instances"
    headers = {"api-key": API_KEY} if API_KEY else {} # Add API key to headers if it exists
    params = {"since": since, "limit": limit}
    for attempt in range(max_retries + 1):
        response = requests.get(url, auth=API_USER, headers=headers, params=params)
        if response.status_code == 200:
            return response.json() #Successful response, return the list of instance IDs
        if attempt < max_retries: 
            time.sleep(2) #Unsuccessful response, but we have retries left, so wait and try again
        else:
            print(f"Error fetching instances at {since} to {since+limit} after {max_retries} attempts: {response.status_code} - {response.text}")
            # TO DO!! ENSURE THIS END UP IN THE QUARANTINE LOG, AND POSSIBLY THAT THIS BATCH OF INSTANCES IS SKIPPED IN THE FUTURE, OTHERWISE WE WILL KEEP TRYING TO PROCESS THIS BATCH AND FAILING EVERY TIME
    response.raise_for_status()
    return response.json()

def get_instance_tags(instance_id, max_retries=2):
    url = f"{ORTHANC_URL}/instances/{instance_id}/simplified-tags"
    headers = {"api-key": API_KEY} if API_KEY else {}
    for attempt in range(max_retries + 1):
        response = requests.get(url, auth=API_USER, headers=headers)
        if response.status_code == 200:
            return response.json()
        if attempt < max_retries:
            time.sleep(2)
        else:
            add_to_quarantine([instance_id], LOG_FILE_QUARANTINE) # Add to quarantine log if we fail to get the tags after retries
            # TO DO!! ENSURE WE ADD +1 to num_quarantined in the main function if we end up here, otherwise the count of quarantined instances will be wrong
    
    response.raise_for_status()

def safe_get(tags, key):
    value = tags.get(key)
    return value if value not in ["", None] else None

def safe_float(value): # Convert a value to float, but return None if it is not possible
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def extract_relevant_dicomtags(tags):
    acquisition_date = safe_get(tags, "AcquisitionDate") or safe_get(tags, "StudyDate") # Sometimes AcquisitionDate does not exist
    
    return {
        "SOPInstanceUID": safe_get(tags, "SOPInstanceUID"),
        "InstitutionName": safe_get(tags, "InstitutionName") or ORTHANC_URL,
        "AcquisitionDate": pd.to_datetime(acquisition_date, format='%Y%m%d', errors='coerce'),
        "PatientBirthDate": safe_get(tags, "PatientBirthDate"),
        "Modality": safe_get(tags, "Modality"),
        "BodyPartExamined": safe_get(tags, "BodyPartExamined"),
        "ExposureIndex": safe_float(safe_get(tags, "ExposureIndex")),
        "TargetExposureIndex": safe_float(safe_get(tags, "TargetExposureIndex")),
    }

def build_dataframe(instances):
    """Build a DataFrame with relevant DICOM tags for the given instance IDs"""
    data = []

    for instance_id in instances:
        try:
           tags = get_instance_tags(instance_id)
           row = extract_relevant_dicomtags(tags)
           row["InstanceID"] = instance_id 
           data.append(row)
        except Exception as e:
            print(f"Error processing {instance_id}: {e}")
            add_to_quarantine([instance_id], LOG_FILE_QUARANTINE)

    df = pd.DataFrame(data)
    if not df.empty:
        cols = ["InstanceID"] + [col for col in df.columns if col != "InstanceID"]
        return df[cols]
    else:
        return None

def append_to_excel(df_new: pd.DataFrame, excel_path: str):
    """Append new rows to the Excel file, or create it if it doesn't exist."""
    if os.path.exists(excel_path):
        df_existing = pd.read_excel(excel_path)
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    else:
        df_combined = df_new

    # Write to a temp file first, then replace the real file only if writing succeeded
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp_path = tmp.name

    df_combined.to_excel(tmp_path, index=False)
    shutil.move(tmp_path, excel_path)

    print(f"Excel updated: {len(df_combined)} total rows ({len(df_new)} new)")

def add_to_success_log(instance_ids: list, log_path: str):
    """Append new instance IDs to the log file."""
    with open(log_path, "a") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"----- {timestamp} -----\n")
        for id_ in instance_ids:
            f.write(f"{id_}\n")

def add_to_quarantine(instance_ids: list, log_path: str):
    """Append quarantined instance IDs to the log file."""
    with open(log_path, "a") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"----- Quarantined: {timestamp} -----\n")
        for id_ in instance_ids:
            f.write(f"{id_}\n")


#####################################################################
################## MAIN FUNCTION  ###################################
#####################################################################

def main_orthanc():

    print("Start processing instances using URL:", ORTHANC_URL)

    #0. Start counting variables
    since = 0
    num_processed_successful = 0
    num_quarantined = 0
    num_already_processed = 0
    num_instances_found = 0
    
    while True:
        # 1. Get all instances
        instances = get_all_instances(since=since, limit=BATCH_SIZE) # Later replace by filter to get only recent XRays
        num_instances_found = num_instances_found + len(instances)

        # Break from the loop if no instances were found
        if not instances:
            break
        
        # 2. Filter to instances that are not in logs yet, by comparing to the log file of already-processed instance IDs. This way we can process only new instances that have been added since the last run.
        existing_ids = get_existing_instance_ids(LOG_FILE_SUCCESS, LOG_FILE_QUARANTINE)
        new_instances = [inst for inst in instances if inst not in existing_ids]
        num_already_processed = num_already_processed + (len(instances) - len(new_instances)) # Update the count of already processed instances

        if not new_instances:
            if len(instances) < BATCH_SIZE:
                break
            since = since + len(instances)
            continue
     
        # 3. Build dataframe with relevant tags
        df = build_dataframe(new_instances)
        
        if df is None or df.empty: # No valid data extracted from the instances
            if len(instances) < BATCH_SIZE:
                break # we reached the end of the list
            since = since + len(instances) # Update the offset to the next batch
            continue

        # 4. Filter out Modality that are xray, these need to be added to the excel (df_DM). Add the others to the quarantine log file.
        to_quarantine = df[~df["Modality"].isin(["DX", "CR"])] # Make a list for quarantine log
        num_quarantined = num_quarantined + len(to_quarantine) # Update the count of quarantined instances
        df = df[df["Modality"].isin(["DX", "CR"])] # Keep only the XRays for further processing
        add_to_quarantine(to_quarantine["InstanceID"].tolist(), LOG_FILE_QUARANTINE)
        if df.empty:
            # All instances in this batch are not XRays, so we skip the rest of the processing and move to the next batch
            if len(instances) < BATCH_SIZE:
                break # we reached the end of the list
            since = since + len(instances)
            continue

        # 5. Filter out instances with missing required fields that are essential for analysis, and add them to quarantine log file.
        missing_bodypart = df["BodyPartExamined"].isnull()
        missing_exposure = df["ExposureIndex"].isnull()
        if missing_bodypart.any() or missing_exposure.any():
            print("Warning: Some instances are missing BodyPartExamined or ExposureIndex. These will be skipped.")
            to_quarantine = df[missing_bodypart | missing_exposure] # Make a list for quarantine log
            num_quarantined = num_quarantined + len(to_quarantine) # Update the count of quarantined instances
            df = df[~(missing_bodypart | missing_exposure)] # Keep only those that have all required fields
            add_to_quarantine(to_quarantine["InstanceID"].tolist(), LOG_FILE_QUARANTINE)  
        if df.empty: 
            # All instances are missing required fields, so we skip the rest of the processing and move to the next batch
            if len(instances) < BATCH_SIZE:
                break # we reached the end of the list
            since = since + len(instances)
            continue
  
        # 6. Add TEI_MSF, DI_MSF, and DI_MSF_Category
        df = add_TEI_DI(df)

        # 7. Append to Excel and log file
        append_to_excel(df, EXCEL_FILE)
        add_to_success_log(df["InstanceID"].tolist(), LOG_FILE_SUCCESS) 
        num_processed_successful = num_processed_successful + len(df) # Update the number of processed instances

        # 8. Update while loop
        if len(instances) < BATCH_SIZE:
            break # we reached the end of the list, so quit the while loop
        since = since + len(instances)

    # Processing done! Add final message.
    print("Processing completed.")
    print("Total instances successfully processed:", num_processed_successful, "out of", num_instances_found, ".") 
    print("Total instances that were already processed:", num_already_processed, "out of", num_instances_found, ".")
    print("Total instances that were quarantined:", num_quarantined, "out of", num_instances_found, ".")

if __name__ == "__main__":
    main_orthanc()