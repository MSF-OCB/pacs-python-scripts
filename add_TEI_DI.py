
from tei_lookup import TEI_MSF_LOOKUP
import pandas as pd
import numpy as np


def add_TEI_DI(df):

    # First set BodyPartExamined to default "Chest" if it is empty
    if df["BodyPartExamined"].isnull().any():
        print("Warning: Some BodyPartExamined values are missing. Setting them to 'Chest' by default.")
        df["BodyPartExamined"] = df["BodyPartExamined"].fillna("Chest")
   
    # For now, since in our testdata ExposureIndex is not provided, set ExposureIndex to random values between 50 and 1000
    if df["ExposureIndex"].isnull().any():
        print("Warning: Some ExposureIndex values are missing. Setting them to random values between 50 and 1000 for testing purposes.")
        df["ExposureIndex"] = df["ExposureIndex"].fillna(pd.Series(np.random.randint(50, 1000, size=len(df))))
   
    # Add TEI_MSF
    df["TEI_MSF"] = df["BodyPartExamined"].map(TEI_MSF_LOOKUP.get) #.get to return NaN for missing values instead of raising an error

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