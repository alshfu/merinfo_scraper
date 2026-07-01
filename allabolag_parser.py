import time
import random
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException
)

# === CONFIGURATION ===
OUTPUT_FILE = "org_numbers_kläder.txt"
MAX_PAGES = 500


def setup_driver():
    """Connect to already running Chrome with remote debugging enabled."""
    print("Connecting to existing Chrome on 127.0.0.1:9222...")

    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    print("Driver connected successfully.")
    return driver


def save_org_nr(org_nr: str):
    """Save organization number to file."""
    try:
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            f.write(org_nr + "\n")
        print(f"   [SAVED] {org_nr}")
    except Exception as e:
        print(f"   [ERROR] Could not save {org_nr}: {e}")


def slow_scroll(driver):
    """Smooth scroll to load all cards."""
    print("   📉 Scrolling page...")
    last_height = driver.execute_script("return document.body.scrollHeight")

    while True:
        driver.execute_script("window.scrollBy(0, 900);")
        time.sleep(random.uniform(0.6, 1.1))

        new_height = driver.execute_script("return document.body.scrollHeight")
        current_position = driver.execute_script("return window.pageYOffset + window.innerHeight")

        if current_position >= new_height - 50:
            break
        last_height = new_height

    time.sleep(1.2)


def get_org_nr_from_card(card) -> str | None:
    """Extract Org.nr from a card safely."""
    try:
        # Check if company is in liquidation
        if card.find_elements(By.XPATH, ".//div[contains(text(), 'Likvidator')]"):
            return None

        # Find Org.nr text
        org_element = card.find_element(
            By.XPATH,
            ".//span[contains(@class, 'CardHeader-propertyList') and contains(., 'Org.nr')]"
        )
        text = org_element.text

        match = re.search(r"(\d{6}-\d{4})", text)
        return match.group(1) if match else None

    except (NoSuchElementException, StaleElementReferenceException):
        return None
    except Exception as e:
        print(f"   [WARN] Error parsing card: {e}")
        return None


def main():
    driver = setup_driver()
    wait = WebDriverWait(driver, 15)

    target_url = "https://www.allabolag.se/segmentering?revenueFrom=-156393&revenueTo=500000&proffIndustryCode=10241778&profitFrom=-92557000&profitTo=50000"

    try:
        # Only navigate if we're not already on the target page
        if target_url not in driver.current_url:
            print("Navigating to Allabolag segmentation page...")
            driver.get(target_url)
            time.sleep(3)

        # === MANUAL PAUSE ===
        print("\n" + "=" * 65)
        print("🚦 SCRIPT PAUSED")
        print("   1. Set your filters on Allabolag in the Chrome window.")
        print("   2. Wait until the list of companies appears.")
        print("   3. Come back here and press ENTER to start scraping.")
        print("=" * 65 + "\n")
        input(">>> Press ENTER to continue <<<")
        print("\n🚀 Starting scraper...\n")

        page_num = 0

        while page_num < MAX_PAGES:
            page_num += 1
            print(f"=== Page {page_num} ===")

            # Wait for cards to appear
            try:
                wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.SegmentationSearchResultCard-card")
                ))
            except TimeoutException:
                print("🛑 No cards found. Possibly reached the end.")
                break

            slow_scroll(driver)

            cards = driver.find_elements(By.CSS_SELECTOR, "div.SegmentationSearchResultCard-card")
            print(f"Found {len(cards)} cards on this page")

            saved_on_page = 0
            for card in cards:
                org_nr = get_org_nr_from_card(card)
                if org_nr:
                    save_org_nr(org_nr)
                    saved_on_page += 1

            print(f"Saved {saved_on_page} companies from page {page_num}")

            # Pagination
            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, "a[aria-label='Go to next page']")

                if "Mui-disabled" in (next_btn.get_attribute("class") or ""):
                    print("\n🏁 Reached the last page.")
                    break

                print("➡️ Going to next page...")
                driver.execute_script("arguments[0].click();", next_btn)
                time.sleep(random.uniform(3.5, 5.5))

            except NoSuchElementException:
                print("\n🏁 No 'Next' button found. End of results.")
                break

    except KeyboardInterrupt:
        print("\n🛑 Script stopped by user.")
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
    finally:
        # Comment out the line below if you want to keep the browser open
        # driver.quit()
        print("\nScript finished.")


if __name__ == "__main__":
    main()