import os
import pandas as pd
import glob

# Paths to the folders
county_dir = os.path.join("data", "regulated_entities_county")
zipcode_dir = os.path.join("data", "regulated_entities_zipcode")
output_path = os.path.join("data", "all_scraped_rns.csv")

print("Collecting CSV file paths...")
# Get all CSV file paths
county_files = glob.glob(os.path.join(county_dir, "*.csv"))
zipcode_files = glob.glob(os.path.join(zipcode_dir, "*.csv"))
all_files = county_files + zipcode_files

print(f"Found {len(county_files)} county files and {len(zipcode_files)} zipcode files.")
print(f"Total files to process: {len(all_files)}")

rn_numbers = []

for i, file_path in enumerate(all_files, 1):
    print(f"[{i}/{len(all_files)}] Processing file: {file_path}")
    try:
        df = pd.read_csv(file_path, dtype=str, encoding='utf-8', on_bad_lines='skip')
        print(f"  - Read {len(df)} rows.")
        df.columns = [col.strip() for col in df.columns]  # Clean column names
        print(df.columns)
        rn_col = next((col for col in df.columns if 'RN' in col), None)
        if rn_col:
            num_rns = df[rn_col].dropna().shape[0]
            print(f"  - Found RN column '{rn_col}' with {num_rns} non-null values.")
            rn_numbers.extend(df[rn_col].dropna().tolist())
        else:
            print("  - No RN column found.")
    except Exception as e:
        print(f"  - Failed to process {file_path}: {e}")

# Create a DataFrame with unique RN numbers
print("Creating DataFrame of unique RN numbers...")
rn_series = pd.Series(rn_numbers).drop_duplicates()
rn_df = pd.DataFrame({'RN Number': rn_series.sort_values().reset_index(drop=True)})

# Save to CSV
os.makedirs(os.path.dirname(output_path), exist_ok=True)
rn_df.to_csv(output_path, index=False)
print(f"Saved {len(rn_df)} unique RN numbers to {output_path}")
