import os
import glob
import logging
from time import sleep
from io import StringIO

import pandas as pd
import zipcodes
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Setup Chrome options
options = webdriver.ChromeOptions()
options.add_argument('--disable-gpu')
options.add_argument('--no-sandbox')
options.add_argument('--window-size=1920x1080')
options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36')

# Constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, '..', 'data', 'regulated_entities_zipcode')
URL = "https://www15.tceq.texas.gov/crpub/index.cfm?fuseaction=regent.RNSearch"
WAIT_TIME = 10

# Get all TX zip codes
tx_zip_codes = [z['zip_code'] for z in zipcodes.filter_by(state="TX")]

def get_processed_zip_codes(path):
    csv_files = glob.glob(os.path.join(path, "*.csv"))
    processed = set()
    for filepath in csv_files:
        try:
            df = pd.read_csv(filepath, usecols=["zipcode"])
            processed.add(os.path.basename(filepath).replace(".csv", "").strip())
        except Exception:
            pass
    return processed

def wait_for_element(driver, by, value, timeout=WAIT_TIME):
    return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, value)))

def parse_single_record_page(html, zip_code):
    soup = BeautifulSoup(html, "html.parser")
    data = {}

    # Section 1: RN Number, Name, Primary Business
    reinfo = soup.find("div", id="reinfo")
    if reinfo:
        rows = reinfo.find_all(["div", "p"])
        for row in rows:
            label = row.find(class_="lbl")
            if label:
                label_text = label.get_text(strip=True).replace(":", "")
                value = row.get_text(strip=True).replace(label.get_text(strip=True), "").strip()
                data[label_text] = value

    # Section 2: Street Address
    street = soup.find("div", id="street_addr")
    if street:
        span = street.find("span", class_="lbl")
        if span:
            label = span.get_text(strip=True).replace(":", "")
            value = street.get_text(strip=True).replace(span.get_text(strip=True), "").strip()
            data[label] = value

    # Section 3: Geo Location
    geo = soup.find("div", id="geo_loc")
    if geo:
        ps = geo.find_all("p")
        for p in ps:
            label = p.find("label")
            if label:
                label_text = label.get_text(strip=True).replace(":", "")
                value = p.get_text(strip=True).replace(label.get_text(strip=True), "").strip()
                data[label_text] = value

    # Add zip for traceability
    data["zipcode"] = zip_code
    return pd.DataFrame([data])

def scrape_zip(driver, zip_code):
    logging.info(f"Starting scrape for ZIP {zip_code}")
    driver.get(URL)

    wait = WebDriverWait(driver, 10)

    try:
        select_program_type = wait.until(EC.presence_of_element_located((By.NAME, 'pgm_area')))
        Select(select_program_type).select_by_value('AIRNSR    ')

        zip_input = driver.find_element(By.ID, 'zip_cd')
        zip_input.clear()
        zip_input.send_keys(zip_code)

        driver.find_element(By.NAME, '_fuseaction=regent.validateRE').click()

        try:
            results_text = wait.until(EC.presence_of_element_located((By.XPATH, '/html/body/div/div[2]/div[2]/span')))
            record_line = results_text.text.strip()
            record_numbers = [s for s in record_line.split() if s.isdigit()]
            if not record_numbers:
                logging.warning(f"No numeric record count found in line: '{record_line}'")
                return 0

            num_records = int(record_numbers[0])
            logging.info(f"{num_records} records found for ZIP {zip_code}")

        except TimeoutException:
            # --- Check for "No results were found" error block ---
            try:
                error_div = driver.find_element(By.CSS_SELECTOR, "div.error")
                if "No results were found for the criteria you entered" in error_div.text:
                    logging.info(f"No results for ZIP {zip_code} — skipping.")
                    return 0
            except:
                pass  # error div not found, continue as single result

            # --- Parse single-record page if error not present ---
            logging.info("Only one result or different page layout — assuming single record.")
            df_single = parse_single_record_page(driver.page_source, zip_code)
            df_single.to_csv(os.path.join(DATA_PATH, f"{zip_code}.csv"), index=False)
            logging.info(f"Finished ZIP {zip_code}, saved 1 row (single record view)")
            return 1

        # --- Multi-record scraping ---
        total_records = []
        df_total_records = pd.DataFrame()

        while len(df_total_records) < num_records:
            logging.info(f"Scraping page {len(total_records) + 1}")
            df = pd.read_html(StringIO(driver.page_source))[0]
            total_records.append(df)
            df_total_records = pd.concat(total_records)

            try:
                next_btn = driver.find_element(By.LINK_TEXT, ">")
                next_btn.click()
                sleep(1)
            except Exception:
                break

        df_total_records["zipcode"] = zip_code
        df_total_records.to_csv(os.path.join(DATA_PATH, f"{zip_code}.csv"), index=False)
        logging.info(f"Finished ZIP {zip_code}, saved {len(df_total_records)} rows")
        return len(df_total_records)

    except Exception as e:
        logging.error(f"Timeout while processing ZIP {zip_code}: {e}")
        with open(os.path.join(DATA_PATH, f"error_{zip_code}.html"), "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        return 0

def main():
    os.makedirs(DATA_PATH, exist_ok=True)
    processed_zips = get_processed_zip_codes(DATA_PATH)
    remaining_zips = [z.strip() for z in tx_zip_codes if z.strip() not in processed_zips]

    # Resume from ZIP code 79159
    START_FROM = "79159"
    remaining_zips = [z for z in remaining_zips if z > START_FROM]

    record_counts_path = os.path.join(DATA_PATH, "record_counts.csv")
    record_counts = []

    logging.info(f"Total ZIPs to process: {len(remaining_zips)}")

    with webdriver.Chrome(service=Service(), options=options) as driver:
        for zip_code in remaining_zips:
            try:
                count = scrape_zip(driver, zip_code)
            except Exception as e:
                logging.exception(f"Failed on ZIP {zip_code}: {e}")
                count = 0
            finally:
                record_counts.append({"zipcode": zip_code, "number_of_records": count})
                pd.DataFrame(record_counts).to_csv(record_counts_path, index=False)

if __name__ == "__main__":
    main()
