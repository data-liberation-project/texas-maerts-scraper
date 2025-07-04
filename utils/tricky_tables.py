import os
import re
import pandas as pd
import numpy as np

def parse_row(split_line: list[str], COLUMNS: list[str]) -> pd.DataFrame:
    """
    Parse a split line into structured columns based on its length patterns.
    Highly customized to specific PDF formats.
    """
    remove_white = [x for x in split_line if x != '']

    if len(remove_white) == 1 and remove_white[0].isdigit():
        # Single numeric entry (e.g., '0') assumed to be Air Contaminant
        emsource = np.nan
        sourcename = np.nan
        air_cont = remove_white[0]
        lbs_hr = np.nan
        tons_year = np.nan
    elif len(remove_white) == 1:
        # Likely a wrapped Source Name
        emsource = np.nan
        sourcename = remove_white[0] if len(remove_white[0]) > 1 else np.nan
        air_cont = np.nan
        lbs_hr = np.nan
        tons_year = np.nan
    elif len(remove_white) == 2 and split_line[0] == '':
        # Likely joined Air Contaminant, lbs/hr and tons/year on one line
        emsource = np.nan
        sourcename = np.nan
        joint_entry = remove_white[0]
        parts = joint_entry.split(" ")
        air_cont = parts[2]
        lbs_hr = parts[3]
        tons_year = remove_white[1]
    elif len(remove_white) == 2:
        # Emission Source and Source Name only
        emsource, sourcename = remove_white
        air_cont = lbs_hr = tons_year = np.nan
    elif len(remove_white) == 3:
        # Air Contaminant, lbs/hr, tons/year
        emsource = sourcename = np.nan
        air_cont, lbs_hr, tons_year = remove_white
    elif len(remove_white) == 4:
        # Source Name, Air Contaminant, lbs/hr, tons/year
        emsource = np.nan
        sourcename, air_cont, lbs_hr, tons_year = remove_white
    else:
        # All five columns present
        emsource, sourcename, air_cont, lbs_hr, tons_year = remove_white[:5]

    return pd.DataFrame([[emsource, sourcename, air_cont, lbs_hr, tons_year]], columns=COLUMNS)


def extract_table_custom(lines: list[str], COLUMNS: list[str]) -> pd.DataFrame:
    """
    Applies parse_row across lines to extract structured data
    when PDFs cannot be table-extracted cleanly.
    """
    total_df = []
    for l in lines:
        split_line = re.split(r'\s{3,}', l)
        try:
            df = parse_row(split_line, COLUMNS)
            total_df.append(df)
        except Exception as e:
            print(f"Parse error on line: {l}\nError: {e}")
    return pd.concat(total_df, ignore_index=True)


def clean_up_tricky_table(df_pages: pd.DataFrame) -> pd.DataFrame:
    """
    Cleans extracted tricky tables:
    - Merges lines where Air Contaminant Names are broken across rows.
    - Merges lines where Source Names are broken across rows.
    """
    # Forward fill Emission Source to handle missing cells
    df_pages['Emission Source'] = df_pages['Emission Source'].ffill()

    cleaned_groups = []
    for group_name, group in df_pages.groupby("Emission Source"):
        # Fill missing with 'empty' for easy checks
        group = group.fillna({'Emission Rate lbs/hr': 'empty', 
                              'Emission Rate tons/year': 'empty', 
                              'Source Name': 'empty'})

        merged_rows = []
        for _, row in group.iterrows():
            # Merge rows where Air Contaminant Name is split
            if row['Emission Rate lbs/hr'] == 'empty' and row['Emission Rate tons/year'] == 'empty' and row['Source Name'] == 'empty':
                if merged_rows:
                    prev = merged_rows.pop()
                    prev['Air Contaminant Name'] = f"{prev['Air Contaminant Name']}_{row['Air Contaminant Name']}"
                    merged_rows.append(prev)
                else:
                    merged_rows.append(row)
            else:
                merged_rows.append(row)

        cleaned_groups.append(pd.DataFrame(merged_rows))

    df_cleaned = pd.concat(cleaned_groups, ignore_index=True)
    df_cleaned['Source Name'] = df_cleaned['Source Name'].replace("empty", np.nan)
    print(f"Tricky cleanup: {len(df_pages)} → {len(df_cleaned)} rows after Air Contaminant merging.")

    # Handle Source Name wrap merging
    final_rows = []
    temp_block = []
    for idx, row in df_cleaned.iterrows():
        if row['Emission Rate lbs/hr'] == 'empty' and row['Emission Rate tons/year'] == 'empty':
            temp_block.append(row)
        elif temp_block:
            # Merge Source Names across wrapped rows
            merged_row = temp_block[0].copy()
            merged_row['Source Name'] = " ".join(str(r['Source Name']) for r in temp_block)
            final_rows.append(merged_row)
            final_rows.append(row)
            temp_block = []
        else:
            final_rows.append(row)

    df_final = pd.DataFrame(final_rows)
    df_final['Source Name'] = df_final['Source Name'].ffill()
    print(f"Tricky cleanup: {len(df_cleaned)} → {len(df_final)} rows after Source Name merging.")

    return df_final