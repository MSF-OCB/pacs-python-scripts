
from tei_lookup import TEI_MSF_LOOKUP
import pandas as pd
import numpy as np


def add_TEI_DI(df):

    # First set BodyPartExamined to default "Chest" if it is empty
    if df["BodyPartExamined"].isnull().any():
        print("Warning: Some BodyPartExamined values are missing. Setting them to 'CHEST*' by default.")
        df["BodyPartExamined"] = df["BodyPartExamined"].fillna("CHEST*")
   
    # Add TEI_MSF, since TargetExposureIndex is not always set correctly and/or provided we have our own TEI
    df["TEI_MSF"] = df["BodyPartExamined"].map(TEI_MSF_LOOKUP.get) #.get to return NaN for missing values instead of raising an error

    # First compute DI (with TargetExposureIndex from DicomFiles), but only when both ExposureIndex and TargetExposureIndex are >0, otherwise set to NaN
    df["DI"] = np.where(
            (df["ExposureIndex"] > 0) & (df["TargetExposureIndex"] > 0),
            round(10 * np.log10(df["ExposureIndex"] / df["TargetExposureIndex"]),2),
            np.nan
            )

    # Compute DI_MSF
    mask = (df["ExposureIndex"] > 0) & (df["TEI_MSF"] > 0) #compute only when EI And TEI are >0
    ratio = df["ExposureIndex"] / df["TEI_MSF"]
    ratio = ratio.astype(float) # Ensure the ratio is float for log10 calculation
    di_values = (10 * np.log10(ratio.where(mask))).round(2)
    df["DI_MSF"] = np.where(mask, di_values, np.nan)

    # Also add DI_MSF_Category because it's used in Power BI and it is easier to add it here
    def di_category(di):
        if di <= -6:
            return "DI <= -6"
        elif (-6 < di <= -3):
            return "-6 < DI <= -3"
        elif (-3 < di < 3):
            return "-3 < DI < 3"
        elif (3 <= di < 6):
            return "3 <= DI < 6"
        elif di >= 6:
            return "DI >= 6"

    df["DI_MSF_Category"] = df["DI_MSF"].apply(di_category)

    return df