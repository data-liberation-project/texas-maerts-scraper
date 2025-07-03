# Library imports
import os
import time
import shutil
import glob
import logging
import tempfile
from io import StringIO
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from dotenv import load_dotenv
from PyPDF2 import PdfReader

# Load environment variables
load_dotenv()

# Constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, '..', 'data', 'raw_pdfs')
RNS_CSV_PATH = os.path.join(BASE_DIR, '..', 'data', "rns_by_zipcode.csv")
DOWNLOAD_COUNTS_PATH = os.path.join(BASE_DIR, 'download_counts.csv')
DOWNLOAD_LOGS_PATH = os.path.join(BASE_DIR, 'download_logs.csv')

os.makedirs(DATA_PATH, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Helper functions
def read_rn_numbers_and_zipcodes(csv_path):
    df = pd.read_csv(csv_path)
    df = df.dropna(subset=['rn_number', 'zipcode'])
    return df[['rn_number', 'zipcode']].drop_duplicates()

def wait_for_download(directory, timeout=30):
    seconds = 0
    while seconds < timeout:
        files = glob.glob(f"{directory}/*")
        if files:
            return max(files, key=os.path.getctime)
        time.sleep(1)
        seconds += 1
    return None

def validate_pdf(file_path):
    try:
        with open(file_path, 'rb') as f:
            PdfReader(f)
        return True
    except Exception as e:
        logging.warning(f"Invalid PDF detected: {file_path}. Error: {e}")
        return False

def init_driver(download_dir):
    options = webdriver.ChromeOptions()
    prefs = {"download.default_directory": download_dir, "plugins.always_open_pdf_externally": True}
    options.add_experimental_option("prefs", prefs)
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(5)
    return driver

def safe_click(driver, by, value, retries=3, description=None):
    for attempt in range(retries):
        try:
            el = driver.find_element(by, value)
            logging.info(f"Clicking: {description or value}")
            el.click()
            return True
        except Exception as e:
            logging.warning(f"Attempt {attempt + 1} failed to click [{description or value}]: {e}")
            time.sleep(1)
    logging.error(f"Failed to click element after {retries} attempts: [{description or value}]")
    return False

def wait_for_results_or_empty(driver, rn, zipcode, timeout=10):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            if driver.find_element(By.XPATH, '//span[contains(text(), "Found 0 potential items")]'):
                logging.info(f"(Zip: {zipcode}) No MAERT found for RN {rn}.")
                return False
        except NoSuchElementException:
            pass
        try:
            driver.find_element(By.XPATH, '/html/body/table[1]/tbody/tr[5]/td/table/tbody/tr/td/div/table[3]/tbody/tr/td[2]/table')
            logging.info("Results table found.")
            return True
        except NoSuchElementException:
            pass
        time.sleep(0.5)
    logging.warning("Timeout while waiting for results or empty message.")
    return False

def log_downloaded_file(rn_number, file_name, zipcode):
    row = pd.DataFrame([{'rn_number': rn_number, 'file_name': file_name, 'zipcode': zipcode}])
    if not os.path.exists(DOWNLOAD_LOGS_PATH):
        row.to_csv(DOWNLOAD_LOGS_PATH, index=False)
    else:
        row.to_csv(DOWNLOAD_LOGS_PATH, mode='a', header=False, index=False)

def load_logged_rns():
    if os.path.exists(DOWNLOAD_LOGS_PATH):
        df = pd.read_csv(DOWNLOAD_LOGS_PATH)
        return set(df['rn_number'].unique())
    return set()

def scrape_maert_for_rns(rn_zip_df):
    downloaded_rns = load_logged_rns()

    for _, row in rn_zip_df.iterrows():
        rn = row['rn_number']
        zipcode = str(row['zipcode'])

        if rn in downloaded_rns:
            logging.info(f"Skipping already logged RN: {rn} (Zip: {zipcode})")
            continue

        logging.info(f"Processing RN: {rn} (Zip: {zipcode})")

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                driver = init_driver(tmp_dir)
                driver.get("https://records.tceq.texas.gov/cs/idcplg?IdcService=TCEQ_SEARCH")

                try:
                    Select(driver.find_element(By.ID, 'xRecordSeries')).select_by_value('1081')
                    Select(driver.find_element(By.ID, 'xInsightDocumentType')).select_by_value('27')
                    Select(driver.find_element(By.XPATH, '/html/body/table[1]/tbody/tr[5]/td/table/tbody/tr/td/div/form/table/tbody/tr[4]/td/table/tbody/tr[1]/td[1]/select')).select_by_value('xRefNumTxt')
                except Exception as e:
                    logging.error(f"Failed to select dropdowns: {e}")
                    driver.quit()
                    continue

                try:
                    driver.find_element(By.XPATH, '/html/body/table[1]/tbody/tr[5]/td/table/tbody/tr/td/div/form/table/tbody/tr[4]/td/table/tbody/tr[1]/td[2]/input').send_keys(rn)
                    safe_click(driver, By.XPATH, '/html/body/table[1]/tbody/tr[5]/td/table/tbody/tr/td/div/form/table/tbody/tr[4]/td/table/tbody/tr[5]/td[3]/div/button[1]', description='Search button')

                    if not wait_for_results_or_empty(driver, rn, zipcode):
                        driver.quit()
                        continue
                except Exception as e:
                    logging.error(f"Failed to enter RN or click Search: {e}")
                    driver.quit()
                    continue

                try:
                    select_element = driver.find_element(By.XPATH, "//select[contains(@name, 'pageSelectList')]")
                    select = Select(select_element)
                    total_pages = len(select.options)
                except Exception:
                    total_pages = 1
                
                maert_downloaded = False

                for page_index in range(total_pages):
                    if total_pages > 1:
                        try:
                            select_element = driver.find_element(By.XPATH, "//select[contains(@name, 'pageSelectList')]")
                            select = Select(select_element)
                            select.select_by_index(page_index)
                            time.sleep(2)
                        except Exception as e:
                            logging.warning(f"Failed to select page {page_index+1}: {e}")
                            break

                    try:
                        table_el = driver.find_element(By.XPATH, '/html/body/table[1]/tbody/tr[5]/td/table/tbody/tr/td/div/table[3]/tbody/tr/td[2]/table')
                        table_html = table_el.get_attribute('outerHTML')
                        df = pd.read_html(StringIO(table_html))[0]
                        maerts = df[df.iloc[:, 12] == 'MAERT']
                    except Exception as e:
                        logging.warning(f"[Page {page_index+1}] Table parsing failed: {e}")
                        continue

                    for hyperlink, permit_number, date in zip(maerts.iloc[:, 2], maerts.iloc[:, 6], maerts.iloc[:, 16]):
                        try:
                            logging.info(f"(Zip: {zipcode}) Downloading permit {permit_number} for RN {rn}")
                            safe_click(driver, By.LINK_TEXT, hyperlink, description=f"MAERT link: {hyperlink}")
                            downloaded = wait_for_download(tmp_dir)
                            if downloaded and validate_pdf(downloaded):
                                unique_id = int(time.time() * 1e6)
                                formatted_date = date.split()[0].replace('/', '-')
                                final_name = f"{zipcode}_{permit_number}_{formatted_date}_{unique_id}.pdf"
                                final_path = os.path.join(DATA_PATH, final_name)
                                shutil.move(downloaded, final_path)
                                logging.info(f"(Zip: {zipcode}) Saved to {final_path}")
                                log_downloaded_file(rn, final_name, zipcode)
                                maert_downloaded = True
                            else:
                                logging.warning(f"(Zip: {zipcode}) Invalid or missing PDF for {permit_number}")
                        except Exception as err:
                            logging.warning(f"(Zip: {zipcode}) Error downloading {permit_number}: {err}")
                    
                if not maert_downloaded:
                    logging.info(f"(Zip: {zipcode}) No MAERT found for RN {rn}.")

                driver.quit()

        except Exception as e:
            logging.error(f"(Zip: {zipcode}) Error processing RN {rn}: {e}")

if __name__ == '__main__':
    rn_zip_df = read_rn_numbers_and_zipcodes(RNS_CSV_PATH)
    scrape_maert_for_rns(rn_zip_df)
