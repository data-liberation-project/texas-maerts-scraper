import os
import sys
import logging
from time import sleep
from io import StringIO
import pandas as pd
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.common.exceptions import TimeoutException

import argparse

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
DATA_PATH = os.path.join(BASE_DIR, '..', 'data')
URL = "https://www15.tceq.texas.gov/crpub/index.cfm?fuseaction=regent.RNSearch"
WAIT_TIME = 10

def wait_for_element(driver, by, value, timeout=WAIT_TIME):
    return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, value)))

def parse_single_record_page(html, zip_code):
    soup = BeautifulSoup(html, "html.parser")
    data = {}

    reinfo = soup.find("div", id="reinfo")
    if reinfo:
        rows = reinfo.find_all(["div", "p"])
        for row in rows:
            label = row.find(class_="lbl")
            if label:
                label_text = label.get_text(strip=True).replace(":", "")
                value = row.get_text(strip=True).replace(label.get_text(strip=True), "").strip()
                data[label_text] = value

    street = soup.find("div", id="street_addr")
    if street:
        span = street.find("span", class_="lbl")
        if span:
            label = span.get_text(strip=True).replace(":", "")
            value = street.get_text(strip=True).replace(span.get_text(strip=True), "").strip()
            data[label] = value

    geo = soup.find("div", id="geo_loc")
    if geo:
        ps = geo.find_all("p")
        for p in ps:
            label = p.find("label")
            if label:
                label_text = label.get_text(strip=True).replace(":", "")
                value = p.get_text(strip=True).replace(label.get_text(strip=True), "").strip()
                data[label_text] = value

    data["zipcode"] = zip_code
    return pd.DataFrame([data])

def scrape_zip(driver, zip_code):
    logging.info(f"Scraping ZIP {zip_code}")
    driver.get(URL)

    try:
        wait_for_element(driver, By.NAME, 'pgm_area')
        Select(driver.find_element(By.NAME, 'pgm_area')).select_by_value('AIRNSR    ')

        zip_input = driver.find_element(By.ID, 'zip_cd')
        zip_input.clear()
        zip_input.send_keys(zip_code)

        driver.find_element(By.NAME, '_fuseaction=regent.validateRE').click()

        try:
            results_text = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, '/html/body/div/div[2]/div[2]/span')))
            record_line = results_text.text.strip()
            record_numbers = [s for s in record_line.split() if s.isdigit()]
            if not record_numbers:
                logging.warning(f"No numeric record count found in: '{record_line}'")
                return pd.DataFrame()

            num_records = int(record_numbers[0])
            logging.info(f"Found {num_records} records for ZIP {zip_code}")

        except TimeoutException:
            try:
                error_div = driver.find_element(By.CSS_SELECTOR, "div.error")
                if "No results were found" in error_div.text:
                    logging.info(f"No results for ZIP {zip_code}. Skipping.")
                    return pd.DataFrame()
            except:
                pass
            logging.info("Assuming single record view.")
            return parse_single_record_page(driver.page_source, zip_code)

        # Multi-record page scraping
        dfs = []
        while True:
            try:
                df = pd.read_html(StringIO(driver.page_source))[0]
                df["zipcode"] = zip_code
                dfs.append(df)

                next_btn = driver.find_element(By.LINK_TEXT, ">")
                next_btn.click()
                sleep(1)
            except Exception:
                break

        combined_df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
        return combined_df

    except Exception as e:
        logging.error(f"Error scraping ZIP {zip_code}: {e}")
        return pd.DataFrame()

def main():
    parser = argparse.ArgumentParser(description="Scrape RN numbers for one or more zipcodes and save a combined CSV.")
    parser.add_argument('zipcodes', nargs='+', help="One or more Texas zipcodes to scrape.")
    parser.add_argument('--output', default='rns_by_zipcode.csv',
                        help="Output CSV filename (default: rns_by_zipcode.csv)")
    args = parser.parse_args()

    os.makedirs(DATA_PATH, exist_ok=True)
    output_path = os.path.join(DATA_PATH, args.output)

    combined_results = []

    with webdriver.Chrome(service=Service(), options=options) as driver:
        for zip_code in args.zipcodes:
            df = scrape_zip(driver, zip_code)
            if not df.empty:
                combined_results.append(df)

    if combined_results:
        final_df = pd.concat(combined_results, ignore_index=True)
        final_df.to_csv(output_path, index=False)
        logging.info(f"Saved {len(final_df)} total rows to {output_path}")
    else:
        logging.info("No data found for provided zipcodes. No CSV generated.")

if __name__ == "__main__":
    main()
