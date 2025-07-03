from selenium import webdriver
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support.expected_conditions import presence_of_element_located
from selenium.common.exceptions import TimeoutException
import pandas as pd
from io import StringIO
import os
import time

# Constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, '..', 'data', 'regulated_entities_county')
URL = "https://www15.tceq.texas.gov/crpub/index.cfm?fuseaction=regent.RNSearch"
WAIT_TIME = 10

# Ensure output directory exists
os.makedirs(DATA_PATH, exist_ok=True)

# Setup
driver = webdriver.Chrome()
wait = WebDriverWait(driver, WAIT_TIME)

# Track record counts for CSV
record_counts = []

# Go to the main page and collect valid county indices
driver.get(URL)
wait.until(presence_of_element_located((By.NAME, 'cnty_name')))
initial_county_options = Select(driver.find_element(By.NAME, 'cnty_name')).options

county_indices = [
    i for i, option in enumerate(initial_county_options)
    if option.get_attribute("value").strip() != ""
]

# Loop through all valid counties
for county_index in county_indices:
    try:
        driver.get(URL)
        wait.until(presence_of_element_located((By.NAME, 'cnty_name')))

        # Select program type
        select_program_type = Select(driver.find_element(By.NAME, 'pgm_area'))
        select_program_type.select_by_value('AIRNSR    ')

        # Select county
        select_county = Select(driver.find_element(By.NAME, 'cnty_name'))
        select_county.select_by_index(county_index)
        selected_option_text = select_county.first_selected_option.text.strip()
        print(f"Filtering for {selected_option_text} (index {county_index})")

        # Submit the form
        driver.find_element(By.NAME, '_fuseaction=regent.validateRE').click()

        # Wait for results
        try:
            number_of_records = wait.until(
                presence_of_element_located((By.XPATH, '/html/body/div/div[2]/div[2]/span'))
            )
            number_of_records_int = int(number_of_records.text)
            print(f"{number_of_records_int} records found.")
        except TimeoutException:
            print("⚠️ Failed to load number of records for:", selected_option_text)
            record_counts.append({"county": selected_option_text, "number of records": 0})
            continue

        total_records = []

        # Paginated scraping
        while len(total_records) < number_of_records_int:
            df = pd.read_html(StringIO(driver.page_source))[0]
            total_records.append(df)

            try:
                next_button = driver.find_element(By.LINK_TEXT, ">")
                if next_button.is_enabled():
                    next_button.click()
                    time.sleep(1.5)  # Give the page time to reload
                else:
                    break
            except:
                break

        # Save the data
        df_total_records = pd.concat(total_records)
        safe_filename = f"{selected_option_text.replace('/', '-')}.csv"
        filepath = os.path.join(DATA_PATH, safe_filename)
        df_total_records.to_csv(filepath, index=False)
        print(f"✅ Saved data to: {filepath}\n")

        # Log number of records
        record_counts.append({"county": selected_option_text, "number of records": len(df_total_records)})

    except Exception as e:
        print(f"❌ Error processing county index {county_index}: {e}")
        record_counts.append({"county": selected_option_text, "number of records": 0})
        continue

# Write the record counts CSV
df_counts = pd.DataFrame(record_counts)
df_counts.to_csv(os.path.join(DATA_PATH, "record_counts.csv"), index=False)
print("Saved record_counts.csv")

driver.quit()
print("All counties processed!")
