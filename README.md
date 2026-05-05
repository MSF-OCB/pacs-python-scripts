
Tool to retrieve the ExposureIndex from X-Ray files in an Orthanc database. 
For each instance in the database, the ExposureIndex is compared to the TargetExposureIndex, and appended to an Excel File.

## Requirements
git clone https://github.com/MSF-OCB/pacs-python-scripts.git
cd pacs-python-scripts
pip install -r requirements.txt

## Configuration
1. .env
cp .env.example .env
fill it:
API_KEY = "yourOrthancAPIKey"
ORTHANC_URL = "yourOrthancUrl" 
API_USERNAME = "yourUsername"
API_PASSWORD = "yourPassword"
2. HardCoded in main_orthanc.py
EXCEL_FILE = "dose_data.xlsx"
LOG_FILE = "orthanc_dosemonitoring.log"
BATCH_SIZE = 500

## Usage
python main_orthanc.py

Summary of steps taken by the code:
1. Get all instances in the database.
2. Filter to instances that are not in logs yet.
3. Build dataframe with relevant tags. Every row is an instance.
4. Filter out Modality that are XR: Only Modalities "DX" "CR" are added to the Excel. Other modalities are added to the log files, such that they are not processed in the future. 
5. Add TEI_MSF, DI_MSF, and DI_MSF_Category.
6. Append to Excel and log file.
7. Save the offset for the next run - Offset is per OrthancUrl, so a different OrthancUrl will start at a different offset.

## Run time files
- `dose_data.xlsx` - Every row is an X-ray instance, with relevant DicomTags and DI, TEI
- `orthanc_dosemonitoring.log` - A list of Instances that have already been processed
- `offset.json` -tracks how many DICOM instances have been processed. 
  Auto-created on first run.

## Error handling and management of the script
- If BodyPartExamined is not filled in, then it's set to default CHEST* and TEI_MSF CHEST is added. Therefore, there is always a DI_MSF output.
- If TEI does not exist in the DicomTags, no DI is outputted. 
- If InstitutionName is empty, the ORTHANC_URL will be added here instead
- Note that you can manually set offset.json to 0 if you want to process the whole database again. It will not create double entries in the Excel, since the log files are scanned for the InstanceIDs that have already been processed.