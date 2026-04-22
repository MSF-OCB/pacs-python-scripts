import requests
from datetime import datetime, timedelta
import pandas as pd
import time
from add_TEI_DI import add_TEI_DI

ORTHANC_URL = "https://demo.orthanc-server.com"

def get_all_instances(): # Not used because we only want recent xray instances, use find_recent_xrays instead
    url = f"{ORTHANC_URL}/instances"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def get_recent_xray_instances(): # THIS DOES NOT WORK? Bacause of Method Not Allowed for url: https://orthanc.uclouvain.be/demo/tools/find, keep calling uclouvain but need demo.orthanc. Somehow cannot fix this.
    # Find all CT instances from the last 6 months (Later replace by X-ray, but there are no Xrays in this dataset)
    six_months_ago = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
    url = f"{ORTHANC_URL}/tools/find"
    print("Calling:", url) # For debugging, check if the correct URL is called

    payload = {
        "Level": "Instance",
        "Query": {
            "Modality": "CT", # Change to xray later, but there are no x-rays in this dataset. Then also fix difference in DX and CR for x rays, I think it's not possible to select both
            "StudyDate": f"{six_months_ago}-"
        }
    }

    r = requests.post(url, json=payload)
    print("Response URL:", r.url)      # Extra for debugging since this seems to go wrong
    print("Status:", r.status_code)

    r.raise_for_status()
    return r.json()

def get_instance_tags(instance_id):
    url = f"{ORTHANC_URL}/instances/{instance_id}/simplified-tags"
    r = requests.get(url)
    r.raise_for_status()
    return r.json()


def safe_get(tags, key):
    value = tags.get(key)
    return value if value not in ["", None] else None

def extract_relevant_dicomtags(tags):
    acquisition_date = safe_get(tags, "AcquisitionDate") or safe_get(tags, "StudyDate") # Sometimes AcquisitionDate does not exist
    
    return {
        "SOPInstanceUID": safe_get(tags, "SOPInstanceUID"),
        "AcquisitionDate": acquisition_date,
        "PatientAge": safe_get(tags, "PatientAge"),
        "Modality": safe_get(tags, "Modality"),
        "BodyPartExamined": safe_get(tags, "BodyPartExamined"),
        "ExposureIndex": safe_get(tags, "ExposureIndex"),
        "TargetExposureIndex": safe_get(tags, "TargetExposureIndex"),
    }

def build_dataframe(instances, limit=100):
    data = []

    for instance_id in instances[:limit]:
        try:
            tags = get_instance_tags(instance_id)
            row = extract_relevant_dicomtags(tags)
            row["InstanceID"] = instance_id 
            data.append(row)

        except Exception as e:
            print(f"Error processing {instance_id}: {e}")

    df = pd.DataFrame(data)
    return df

def main_orthanc():

    #0. Check which URL is used for Orthanc, some issue here, so debugging
    print("Using URL:", ORTHANC_URL)
    
    # 1. Get all instances
    instances = get_all_instances() # Later replace by get_recent_xray_instances() when that works...
    print(f"Found {len(instances)} instances")

    # 2. Build dataframe with relevant tags, do max 50 for now
    df = build_dataframe(instances, limit=100)

    #3. Add TEI_MSF, DI_MSF, and DI_MSF_Category
    df = add_TEI_DI(df)

    # 4. Write df to Excel
    # Later we should do some more logic by writing to an existing Excel and ensuring no duplicates, but for now, just write to a new Excel file
    df.to_excel("dose_data.xlsx", index=False)

if __name__ == "__main__":
    main_orthanc()