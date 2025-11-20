from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import time
import json
import re
import os
import random
import sys
import select

# === CONFIGURATION ===
ORG_NUMBERS_FILE = "org_numbers_bil.txt"
OUTPUT_FILE = "mer_info_complett.jsonl"


def setup_driver():
    """Konfigurerar och startar Chrome Driver för macOS"""
    chrome_options = Options()
    # chrome_options.add_argument("--headless") # Avkommentera om du inte vill se webbläsaren
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--start-maximized")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def clean_text(text):
    """Hjälpfunktion för att städa text från extra mellanslag och nyradstecken"""
    if text:
        return " ".join(text.split())
    return ""


def scroll_page_fully(driver):
    """Skrollar långsamt ner på sidan för att ladda allt dynamiskt innehåll."""
    print("    -> Skrollar sidan för att ladda allt innehåll...")
    last_height = driver.execute_script("return document.body.scrollHeight")
    for _ in range(10): # Skrolla max 10 gånger
        driver.execute_script("window.scrollBy(0, window.innerHeight);")
        time.sleep(random.uniform(0.3, 0.7))
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.5)


def load_and_get_first_org_number():
    """Läser in organisationsnummer och hittar det första som inte är markerat."""
    try:
        with open(ORG_NUMBERS_FILE, 'r', encoding='utf-8') as f:
            all_lines = [line.strip() for line in f if line.strip()]

        unprocessed_numbers = [
            line for line in all_lines
            if not (line.upper().endswith('O') or line.upper().endswith('X') or line.upper().endswith('E'))
        ]

        if not unprocessed_numbers:
            return None, 0

        return unprocessed_numbers[0], len(unprocessed_numbers)
    except FileNotFoundError:
        print(f"⚠️ Varning: Filen '{ORG_NUMBERS_FILE}' hittades inte.")
        print("  Skapar en exempelfil med testdata...")
        with open(ORG_NUMBERS_FILE, "w", encoding="utf-8") as f:
            f.write("556631-3788\n556681-9685\n556679-7394\n556736-5258\n556906-7597")
        return "556631-3788", 5
    except Exception as e:
        print(f"❌ Fel vid läsning av filen: {e}")
        return None, 0


def mark_org_number(org_number_to_mark, status):
    """Markerar ett organisationsnummer i filen med en status (O för OK, E för Fel/Hoppad)."""
    try:
        with open(ORG_NUMBERS_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        new_lines = []
        marked = False
        for line in lines:
            stripped_line = line.strip()
            if stripped_line == org_number_to_mark and not marked:
                new_lines.append(f"{stripped_line}{status.upper()}\n")
                marked = True
            else:
                new_lines.append(line)

        if marked:
            with open(ORG_NUMBERS_FILE, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            print(f"   [UPDATE] Numret {org_number_to_mark} har markerats med '{status.upper()}' i {ORG_NUMBERS_FILE}")
        else:
            print(f"   [!] Varning: Kunde inte hitta det omarkerade numret {org_number_to_mark} att markera.")
    except Exception as e:
        print(f"   [!] Kunde inte uppdatera filen {ORG_NUMBERS_FILE}: {e}")


def save_record(data):
    """Sparar företagets data i JSONL-format."""
    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(data, ensure_ascii=False) + '\n')
    print(f"   [SAVE] Sparat: {data.get('company_info', {}).get('name')}")


def scrape_merinfo_details(driver, org_nr):
    """Skrapar detaljer från företagssidan på Merinfo"""
    print(f"  Samlar data från Merinfo för {org_nr}...")
    scroll_page_fully(driver)
    time.sleep(random.uniform(1.01, 3.03))

    data = {
        "company_info": {}, "contact_info": {}, "business_details": {},
        "financials": {}, "metadata": {}, "key_people": []
    }

    try:
        try: data["company_info"]["name"] = clean_text(driver.find_element(By.CSS_SELECTOR, "h1 .namn").text)
        except: pass
        data["company_info"]["organization_number"] = org_nr
        try: data["company_info"]["location"] = {"city": clean_text(driver.find_element(By.CSS_SELECTOR, "h1 .fa-map-marker-alt + span").text)}
        except: pass
        try: data["contact_info"]["phone"] = {"number": clean_text(driver.find_element(By.CSS_SELECTOR, "a[href^='tel:']").text)}
        except: data["contact_info"]["phone"] = "Ej angivet"
        try:
            address_text = driver.find_element(By.TAG_NAME, "address").text
            data["contact_info"]["address"] = {"full_address": clean_text(address_text), "lines": [clean_text(l) for l in address_text.split('\n') if l.strip()]}
        except: data["contact_info"]["address"] = "Ej angivet"
        try: data["business_details"]["description"] = clean_text(driver.find_element(By.CSS_SELECTOR, ".vue-toggle-fade .expanded").text)
        except: pass
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, ".mi-flex.mi-flex-wrap.mi-py-2.mi-justify-between")
            financials = {}
            for row in rows:
                spans = row.find_elements(By.TAG_NAME, "span")
                if len(spans) >= 2:
                    financials[clean_text(spans[0].text)] = clean_text(spans[1].text)
            data["financials"]["latest_summary"] = financials
        except: pass
        data["metadata"]["source_url"] = driver.current_url
    except Exception as e:
        print(f"  Fel vid skrapning av företagsdetaljer: {e}")
    return data


def get_bankgiro(driver, org_nr):
    """Öppnar Bankgirot i en ny flik, hanterar cookies, hämtar numret och stänger fliken."""
    print(f"  Söker Bankgiro för {org_nr} i en ny flik...")
    original_window = driver.current_window_handle
    bankgiro_nr = "Ej hittat"
    
    try:
        driver.switch_to.new_window('tab')
        driver.get("https://www.bankgirot.se/")
        wait = WebDriverWait(driver, 10)
        try:
            cookie_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Acceptera alla cookies')]")))
            cookie_button.click()
            print("    -> Accepterade cookies på Bankgirot.")
            time.sleep(1)
        except TimeoutException:
            print("    -> Ingen cookie-banner hittades eller kunde inte klickas.")
        
        search_input = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input.start-area-search-orgnr")))
        search_input.clear()
        search_input.send_keys(org_nr)
        driver.find_element(By.CSS_SELECTOR, ".start-area-search form button").click()
        
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "bgnr-results")))
        
        xpath_query = "//li[contains(@class, 'subtitle') and contains(text(), 'Bankgironummer')]/following-sibling::li"
        bankgiro_nr = clean_text(driver.find_element(By.XPATH, xpath_query).text)
        print(f"  ✅ Hittade Bankgiro: {bankgiro_nr}")
        
    except Exception as e:
        print(f"  ❌ Kunde inte hitta Bankgiro: {str(e)}")
    finally:
        driver.close()
        driver.switch_to.window(original_window)
        
    return bankgiro_nr


def scrape_person_details(driver):
    """Skrapar personprofilen. Varje datapunkt är valfri för att undvika krascher."""
    print("    -> Samlar data om person...")
    scroll_page_fully(driver)
    time.sleep(random.uniform(1.01, 3.03))
    
    p_data = {"person_info": {}, "location_info": {}}

    try: p_data["person_info"]["full_name"] = clean_text(driver.find_element(By.CSS_SELECTOR, "h1 .namn").text)
    except Exception: pass
    try:
        pnr_elem = driver.find_element(By.XPATH, "//div[h3[contains(text(), 'Personnummer')]]")
        p_data["person_info"]["personal_number"] = clean_text(pnr_elem.text).replace("Personnummer", "").strip()
    except Exception: pass
    try:
        p_data["person_info"]["raw_header_info"] = clean_text(driver.find_element(By.CSS_SELECTOR, "h1 > div").text)
    except Exception: pass
    p_data["person_info"]["profile_url"] = driver.current_url

    try:
        addr_elem = driver.find_element(By.XPATH, "//div[h3[contains(text(), 'Folkbokföringsadress')]]/address")
        p_data["location_info"]["registered_address"] = clean_text(addr_elem.text)
    except Exception: p_data["location_info"]["registered_address"] = "Ej funnen"

    return p_data


def main():
    driver = None
    first_run = True

    while True:
        current_org_nr, remaining = load_and_get_first_org_number()
        if current_org_nr is None:
            print("🎉 Filen med organisationsnummer är tom. Alla nummer har bearbetats.")
            break

        print(f"\nÅterstående att bearbeta: {remaining} organisationsnummer.")
        print(f"\n=== Bearbetar: {current_org_nr} ===")

        try:
            if driver is None:
                driver = setup_driver()
                if first_run:
                    driver.get("https://www.merinfo.se/")
                    print("\n🚦 MANUELLT STEG: Webbläsaren är öppen på Merinfo.se.")
                    input("   1. Hantera eventuella cookies.\n   2. Installera/logga in på VPN och anslut till en server.\n>>> Tryck på Enter i konsolen när du är klar...")
                    first_run = False
                    print("\n✅ Fortsätter skriptet...")

            wait = WebDriverWait(driver, 10)
            driver.get(f"https://www.merinfo.se/search?q={current_org_nr}")
            time.sleep(1)

            if "Oops, din sökgräns är nådd!" in driver.page_source:
                raise WebDriverException("Sökgränsen har nåtts.")

            try:
                try:
                    cookie_banner_button = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Jag samtycker')]")))
                    cookie_banner_button.click()
                    time.sleep(1)
                except TimeoutException:
                    pass

                result_list = wait.until(EC.presence_of_element_located((By.ID, "result-list")))
                company_link = result_list.find_element(By.XPATH, f".//a[contains(@href, '/foretag/') and contains(@href, '{current_org_nr.replace('-', '')}')]")
                parent_div = company_link.find_element(By.XPATH, "./ancestor::div[contains(@class, 'mi-shadow-dark-blue-20')]")
                if "mi-text-red" in parent_div.get_attribute("innerHTML"):
                     print(f"  ❌ {current_org_nr}: Har anmärkning. Markeras med E.")
                     mark_org_number(current_org_nr, 'E')
                     continue
                print(f"  ✅ {current_org_nr}: Inga anmärkningar. Går vidare...")
                company_link.click()
            except (NoSuchElementException, TimeoutException, WebDriverException) as e:
                 print(f"  ❌ {current_org_nr}: Hittade inte företagskortet eller ett klick-fel uppstod: {e}. Markeras med E.")
                 mark_org_number(current_org_nr, 'E')
                 continue

            company_data = scrape_merinfo_details(driver, current_org_nr)
            company_url = driver.current_url

            bg_number = get_bankgiro(driver, current_org_nr)
            company_data["company_info"]["bankgirot"] = bg_number

            print(f"  Återvänder till {company_url} för att hitta nyckelpersoner...")
            driver.get(company_url)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
            scroll_page_fully(driver)

            people_to_scrape = []
            try:
                person_links = driver.find_elements(By.XPATH, "//table//a[contains(@href, '/person/')]")
                print(f"  Hittade {len(person_links)} potentiella nyckelpersoner.")
                for link in person_links:
                    try:
                        person_url = link.get_attribute('href')
                        role = link.find_element(By.XPATH, "./ancestor::tr/td[1]").text.strip().replace(':', '')
                        if person_url and role and {'url': person_url, 'role': role} not in people_to_scrape:
                            people_to_scrape.append({'url': person_url, 'role': role})
                    except NoSuchElementException: continue
            except Exception as e:
                print(f"  Fel vid insamling av personlänkar: {e}")

            for person in people_to_scrape:
                print(f"  -> Besöker profilsida för roll: {person['role']}")
                driver.get(person['url'])
                person_details = scrape_person_details(driver)
                person_details['role'] = person['role']
                company_data['key_people'].append(person_details)
                print(f"  <- Återvänder till företagssidan...")
                driver.get(company_url)
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "h1")))

            if not people_to_scrape:
                print("  Inga nyckelpersoner med länkar hittades på sidan.")

            if company_data.get("company_info", {}).get("name"):
                save_record(company_data)
                mark_org_number(current_org_nr, 'O')
            else:
                print(f"   [!] Ingen data samlades in för {current_org_nr}, markeras med E.")
                mark_org_number(current_org_nr, 'E')

            # Paus med möjlighet att avbryta
            print("\n⏳ Pausar i 5 sekunder... Tryck Enter för att pausa helt.", end='', flush=True)
            r, _, _ = select.select([sys.stdin], [], [], 5)
            if r:
                input() # Väntar på ett andra Enter för att fortsätta
                print("   Fortsätter...")
            else:
                print("\n   Fortsätter automatiskt...")


        except (TimeoutException, WebDriverException) as e:
            print(f"   [!] Fel vid sidladdning eller webbläsarkommunikation: {e}")
            print("   [RESTART] Startar om webbläsaren...")
            if driver: driver.quit()
            driver = None
            time.sleep(5)
            continue
        except KeyboardInterrupt:
            print("\n🛑 Avbryter skriptet.")
            break
        except Exception as e:
            print(f"   [!] Ett oväntat fel inträffade vid bearbetning av {current_org_nr}: {e}")
            print("   [RESTART] Startar om webbläsaren...")
            if driver: driver.quit()
            driver = None
            time.sleep(10)
            continue

    if driver:
        driver.quit()
    print("\nSkriptet har slutförts.")


if __name__ == "__main__":
    main()
