import json
import os
from urllib import response
import requests
from datetime import datetime, timedelta
import pandas as pd
import time
from add_TEI_DI import add_TEI_DI
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("API_KEY")
ORTHANC_URL = os.getenv("ORTHANC_URL")
API_USERNAME = os.getenv("API_USERNAME")
API_PASSWORD = os.getenv("API_PASSWORD")
API_USER = (API_USERNAME, API_PASSWORD)
EXCEL_FILE = "dose_data.xlsx"
LOG_FILE = "orthanc_dosemonitoring.log"
BATCH_SIZE = 500
OFFSET_FILE = "offset.json"


def load_offset(url):
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE, "r") as f:
            offsets = json.load(f)
            return offsets.get(url, 0)  # return 0 if this URL is new
    return 0

def save_offset(url, since):
    offsets = {}
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE, "r") as f:
            offsets = json.load(f)
    offsets[url] = since
    with open(OFFSET_FILE, "w") as f:
        json.dump(offsets, f, indent=2)

def get_existing_instance_ids(log_path:str) -> set:
   """Read the log file and return a set of already-processed instance IDs."""
   if not os.path.exists(log_path):
        return set()
   with open(log_path, "r") as f:
        return set(line.strip() for line in f if line.strip())
   
def get_all_instances(since=0, limit=50):
    url = f"{ORTHANC_URL}/instances"
    headers = {
        "api-key": API_KEY
    }
    params = {"since": since, "limit": limit}
    response = requests.get(url, auth=API_USER, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def get_instance_tags(instance_id):
    url = f"{ORTHANC_URL}/instances/{instance_id}/simplified-tags"
    headers = {
        "api-key": API_KEY
    }
    r = requests.get(url, auth=API_USER, headers=headers)
    r.raise_for_status()
    return r.json()

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
    df_combined.to_excel(excel_path, index=False)
    print(f"Excel updated: {len(df_combined)} total rows ({len(df_new)} new)")

def append_to_log(instance_ids: list, log_path: str):
    """Append new instance IDs to the log file."""
    with open(log_path, "a") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"----- {timestamp} -----\n")
        for id_ in instance_ids:
            f.write(f"{id_}\n")

def main_orthanc():

    #0. Give some information on what we are going to do
    print("Start processing instances using URL:", ORTHANC_URL)
    
    # 1. Get all instances
    since = load_offset(ORTHANC_URL)
    instances = get_all_instances(since=since, limit=BATCH_SIZE) # Later replace by filter to get only recent XRays
    print(f"Found {len(instances)} instances in the database")

    # 2. Filter to instances that are not in logs yet, by comparing to the log file of already-processed instance IDs. This way we can process only new instances that have been added since the last run.
    existing_ids = get_existing_instance_ids(LOG_FILE)
    new_instances = [inst for inst in instances if inst not in existing_ids]

    if not new_instances:
        print("No new instances to process. Exiting.")
        return
    print(f"Found {len(new_instances)} new instances to process")
     
    # 3. Build dataframe with relevant tags
    df = build_dataframe(new_instances)
    if df is None or df.empty:
        print("No valid data extracted from instances. Exiting.")
        return

    # 4. Filter out Modality that are XR, these need to be added to the excel (df_DM). To the log file, we do add all instances, even those that are not XR, because we want to keep track of which ones we have processed, and we don't want to process them again in the future (df).
    df_DM = df[df["Modality"].isin(["DX", "CR"])]
    if df_DM.empty:
        print("No new XR instances to process. Exiting.")
        append_to_log(df["InstanceID"].tolist(), LOG_FILE) # But still add all instance IDs to the log, so we don't process them again in the future
        return

    # 5. Add TEI_MSF, DI_MSF, and DI_MSF_Category
    df_DM = add_TEI_DI(df_DM)

    # 6. Append to Excel and log file
    append_to_excel(df_DM, EXCEL_FILE) #df_DM because we only want to add the XRays to the Excel file
    append_to_log(df["InstanceID"].tolist(), LOG_FILE) #df because we want to log all processed instances, even those that are not XRays, so we don't process them again in the future

    # 7. Save the offset for the next run
    save_offset(ORTHANC_URL, since + len(instances))
    print(f"Done. Next run will start from {since + len(instances)}.")

if __name__ == "__main__":
    main_orthanc()