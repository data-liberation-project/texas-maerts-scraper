import os
import re
import pdfplumber
import pandas as pd
from pathlib import Path
import logging
import numpy as np
import sys

# ========== PATH SETUP ==========

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from utils import tricky_tables

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(SCRIPT_DIR, '..', 'data')

PDF_DIR = os.path.join(DATA_PATH, 'raw_pdfs')
OUTPUT_DIR = os.path.join(DATA_PATH, 'extracted_csvs')
LOG_PATH = os.path.join(DATA_PATH, 'pdf_processing_log.csv')

os.makedirs(OUTPUT_DIR, exist_ok=True)

COLUMNS = [
    "Emission Source",
    "Source Name",
    "Air Contaminant Name",
    "Emission Rate lbs/hr",
    "Emission Rate tons/year"
]

# ========== LOGGING ==========

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ========== LOG FILE SETUP ==========

if os.path.exists(LOG_PATH):
    log_df = pd.read_csv(LOG_PATH)
else:
    log_df = pd.DataFrame(columns=["filename", "status", "note"])

# ========== MAIN EXTRACTION LOOP ==========

pdf_files = list(Path(PDF_DIR).rglob("*.pdf"))

for pdf_path in pdf_files:
    logging.info("-" * 26)  # separator line before each new file
    logging.info(f"Processing: {pdf_path.name}")
    extracted_pages = []
    tricky_table_found = False

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_num = page.page_number
                text = page.extract_text(keep_blank_chars=True)
                text_simple = page.extract_text()

                table = page.extract_table()
                if table:
                    logging.info(f"Easy table found on page {page_num} of {pdf_path.name}")
                    df_easy = pd.DataFrame(table[1:], columns=table[0])
                    df_easy['Emission Source'] = df_easy['Emission Source'].ffill()
                    df_easy['Source Name'] = df_easy['Source Name'].ffill()
                    extracted_pages.append(df_easy)

                    if text_simple and "point identification" in text_simple:
                        break
                else:
                    logging.info(f"No easy table found on page {page_num}, using tricky extraction.")
                    tricky_table_found = True

                    try:
                        core_pat = re.compile(r"TPY[\-\s]+(.*)\n\s+", re.DOTALL)
                        core = re.search(core_pat, text).group(1)
                    except Exception:
                        core = text

                    lines = core.split("\n")

                    if text_simple and "(1) Emission point identification" in text_simple:
                        idx_list = [i for i, line in enumerate(lines) if "pointidentification" in line.replace(" ", "")]
                        if idx_list:
                            lines = lines[:idx_list[0]]

                    df_tricky = tricky_tables.extract_table_custom(lines, COLUMNS)
                    extracted_pages.append(df_tricky)

                    if text_simple and "(1) Emission point identification" in text_simple:
                        break

        # ========== CLEANUP & COMBINE ==========

        if tricky_table_found:
            combined_df = pd.concat(extracted_pages).dropna(axis=0, how='all').reset_index(drop=True)
            combined_df = tricky_tables.clean_up_tricky_table(combined_df)
        else:
            combined_df = pd.concat(extracted_pages).reset_index(drop=True)

        # Add metadata columns
        split_name = pdf_path.stem.split("_")
        combined_df["filename"] = pdf_path.name
        combined_df["zipcode"] = split_name[0] if len(split_name) > 0 else None
        combined_df["entity"] = split_name[0] if len(split_name) > 0 else None
        combined_df["permit_number"] = split_name[1] if len(split_name) > 1 else None
        combined_df["publish_date"] = split_name[2] if len(split_name) > 2 else None

        # Drop duplicated header rows
        combined_df = combined_df[combined_df["Emission Source"] != "Emission"]

        # Save CSV
        out_csv = os.path.join(OUTPUT_DIR, f"{pdf_path.stem}_extracted.csv")
        combined_df.to_csv(out_csv, index=False)
        logging.info(f"Saved extracted CSV: {out_csv}")

        # Log success
        log_df = pd.concat([
            log_df,
            pd.DataFrame([{
                "filename": pdf_path.name,
                "status": "processed",
                "note": "tricky" if tricky_table_found else "easy"
            }])
        ], ignore_index=True)

    except Exception as e:
        logging.error(f"Failed to process {pdf_path.name}: {e}")

        # Log failure
        log_df = pd.concat([
            log_df,
            pd.DataFrame([{
                "filename": pdf_path.name,
                "status": "failed",
                "note": str(e)
            }])
        ], ignore_index=True)

    # Write updated log after each file
    log_df.to_csv(LOG_PATH, index=False)

logging.info("Done processing all PDFs.")
