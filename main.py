import json
import time
import random
import os
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

# === КОНФИГУРАЦИЯ ===
ORG_NUMBERS_FILE = "org_numbers.txt"
OUTPUT_FILE = "merinfo_complete_assistants.jsonl"


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def clean_text(text):
    """Удаляет лишние пробелы и переносы строк."""
    if not text: return None
    return " ".join(text.split())


def get_table_value(driver, header_text):
    """Ищет значение в стандартных таблицах Merinfo по заголовку (th)."""
    try:
        # Ищем th с текстом, затем соседний td
        xpath = f"//th[contains(., '{header_text}')]/following-sibling::td"
        return clean_text(driver.find_element(By.XPATH, xpath).text)
    except:
        return None


def get_financial_value(driver, label_text):
    """Ищет значения в блоке финансовых показателей (Nyckeltal)."""
    try:
        # Ищем span с названием показателя, затем следующий span с числом
        xpath = f"//span[contains(., '{label_text}')]/following-sibling::span"
        val = driver.find_element(By.XPATH, xpath).text.strip()
        # Очищаем от 'tkr' и пробелов, превращаем в число
        val_clean = val.replace(" tkr", "").replace(" ", "").replace("\xa0", "")
        return int(val_clean) * 1000 if val_clean.lstrip('-').isdigit() else None
    except:
        return None


def parse_address(address_text):
    """Пытается разбить строку адреса на улицу, индекс и город."""
    if not address_text: return {}, {}, {}
    # Пример: "Stuvaregatan 11, 252 67 Helsingborg"
    # Простая регулярка для поиска индекса (5 цифр подряд или 3+2)
    match = re.search(r'(\d{3}\s?\d{2})\s+(.+)', address_text)
    postal_code = match.group(1).replace(" ", "") if match else None
    city = match.group(2).strip() if match else None

    # Все что до индекса - улица
    street = address_text.split(match.group(0))[0].strip().strip(",") if match else address_text

    return street, postal_code, city


# === НАСТРОЙКА DRIVER ===
def setup_driver():
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.page_load_strategy = 'eager'
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver


def save_record(data, org_number, remaining_numbers):
    # 1. Сохраняем данные в JSONL
    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(data, ensure_ascii=False) + '\n')
    print(f"   [SAVE] Сохранено: {data['company'].get('name')}")

    # 2. Обновляем файл с номерами
    try:
        with open(ORG_NUMBERS_FILE, 'w', encoding='utf-8') as f:
            for number in remaining_numbers:
                if number != org_number:
                    f.write(number + '\n')
        print(f"   [UPDATE] Номер {org_number} удален из {ORG_NUMBERS_FILE}")
    except Exception as e:
        print(f"   [!] Не удалось обновить файл {ORG_NUMBERS_FILE}: {e}")


# === ПАРСИНГ ПЕРСОНЫ ===
def get_person_details(driver, person_url, role):
    print(f"   -> [Person] {role}...")
    time.sleep(random.uniform(1.0, 2.5)) # Задержка перед переходом
    driver.get(person_url)

    details = {
        "role": role,
        "name": None,
        "age": None,
        "phone": None,
        "address": {}
    }
    try:
        wait = WebDriverWait(driver, 10)
        details['name'] = clean_text(wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1 span.namn"))).text)

        try:
            age_text = driver.find_element(By.XPATH,
                                           "//i[contains(@class,'fa-address-book')]/following-sibling::span").text
            details['age'] = int(re.search(r'\d+', age_text).group())
        except:
            pass

        try:
            details['phone'] = clean_text(driver.find_element(By.CSS_SELECTOR, "a[href^='tel:']").text)
        except:
            pass

        try:
            addr_full = clean_text(driver.find_element(By.CSS_SELECTOR, "#oversikt address").text)
            apt_match = re.search(r'lgh\s?(\d{4})', addr_full, re.IGNORECASE)
            details['address']['apartment'] = f"lgh {apt_match.group(1)}" if apt_match else None
            street, zip_code, city = parse_address(addr_full.replace(details['address']['apartment'] or "", ""))
            details['address']['street'] = street
            details['address']['postal_code'] = zip_code
            details['address']['city'] = city
        except:
            pass

    except Exception as e:
        print(f"Ошибка персоны: {e}")

    return details


# === ПАРСИНГ ФИРМЫ (ГЛАВНАЯ ФУНКЦИЯ) ===
def process_company(driver, company_url):
    print(f"\n-> [Company] Сбор полных данных...")
    time.sleep(random.uniform(1.0, 2.5)) # Задержка перед переходом
    driver.get(company_url)
    wait = WebDriverWait(driver, 10)

    final_data = {
        "company": {}, "contact": {}, "tax_info": {},
        "financials": {}, "industry": {}, "board": []
    }

    try:
        final_data['company']['name'] = clean_text(
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1 span.namn"))).text)

        try:
            org_text = driver.find_element(By.XPATH, "//h1//i[contains(@class, 'fa-address-book')]/following-sibling::span").text
            final_data['company']['org_number'] = clean_text(org_text)
        except: pass

        final_data['company']['legal_form'] = get_table_value(driver, "Bolagsform:")
        final_data['company']['status'] = get_table_value(driver, "Status:")
        final_data['company']['registration_date'] = get_table_value(driver, "Registrerat:")

        try:
            remark_el = driver.find_element(By.CSS_SELECTOR, ".mi-text-green, .mi-text-red, .mi-text-orange")
            final_data['company']['remarks'] = clean_text(remark_el.text)
            try:
                date_el = remark_el.find_element(By.XPATH, "./following-sibling::span")
                final_data['company']['remarks'] += " " + clean_text(date_el.text)
            except: pass
        except:
            final_data['company']['remarks'] = None

        try:
            phone_el = driver.find_element(By.CSS_SELECTOR, "a[href^='tel:']")
            final_data['contact']['phone'] = clean_text(phone_el.text)
        except: pass
        
        try:
            addr_full = clean_text(driver.find_element(By.TAG_NAME, "address").text)
            addr_full = addr_full.replace(final_data['company']['name'], "").strip().strip(",")
            final_data['contact']['address'] = addr_full
            _, final_data['contact']['postal_code'], final_data['contact']['city'] = parse_address(addr_full)
        except: pass

        final_data['contact']['municipality'] = get_table_value(driver, "Kommunsäte:")
        final_data['contact']['county'] = get_table_value(driver, "Länssäte:")

        f_skatt = get_table_value(driver, "F-Skatt:")
        final_data['tax_info']['f_skatt'] = True if f_skatt and "Ja" in f_skatt else False
        moms = get_table_value(driver, "Momsregistrerad:")
        final_data['tax_info']['vat_registered'] = True if moms and "Ja" in moms else False
        arbetsgivare = get_table_value(driver, "Arbetsgivare:")
        final_data['tax_info']['employer_registered'] = True if arbetsgivare and "Ja" in arbetsgivare else False

        try:
            period_el = driver.find_element(By.XPATH, "//h3[contains(., 'Nyckeltal 20')]")
            final_data['financials']['period'] = period_el.text.replace("Nyckeltal ", "").strip()
        except: pass

        final_data['financials']['currency'] = "SEK"
        final_data['financials']['revenue'] = get_financial_value(driver, "Omsättning")
        final_data['financials']['profit_after_financial_items'] = get_financial_value(driver, "Res. e. fin")
        final_data['financials']['net_profit'] = get_financial_value(driver, "Årets resultat")
        final_data['financials']['total_assets'] = get_financial_value(driver, "Summa tillgångar")

        try:
            sni_full = driver.find_element(By.XPATH, "//h3[contains(., 'Svensk näringsgrensindelning')]/following-sibling::div").text.strip()
            sni_parts = sni_full.split(" - ", 1)
            final_data['industry']['sni_code'] = sni_parts[0] if len(sni_parts) == 2 else None
            final_data['industry']['sni_description'] = sni_parts[1] if len(sni_parts) == 2 else sni_full
        except: pass

        try:
            categories = [clean_text(link.text) for link in driver.find_elements(By.XPATH, "//h3[contains(., 'Bransch')]/following-sibling::div//a")]
            final_data['industry']['categories'] = categories
        except: pass

        try:
            desc_el = driver.find_element(By.XPATH, "//h3[contains(., 'Verksamhetsbeskrivning')]/following-sibling::div//div[contains(@class, 'expanded')]")
            final_data['industry']['activity_description'] = clean_text(desc_el.text)
        except: pass

        roles_to_check = ["VD", "Ordförande", "Styrelseledamot", "Ordinarie ledamot", "Innehavare", "Komplementär", "Likvidator"]
        person_found = False
        for role in roles_to_check:
            try:
                xpath = f"//td[contains(., '{role}')]/following-sibling::td//a[contains(@href, '/person/')]"
                person_link = driver.find_element(By.XPATH, xpath)
                person_url = person_link.get_attribute('href')
                final_data['board'].append(get_person_details(driver, person_url, role))
                print("   <- [Back] Возврат...")
                time.sleep(random.uniform(1.0, 2.5)) # Задержка перед возвратом
                driver.back()
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1 span.namn")))
                person_found = True
                break 
            except NoSuchElementException:
                continue
        if not person_found:
            print("   [i] Ключевая персона не найдена в таблице.")

    except Exception as e:
        print(f"   [!] Ошибка при сборе данных: {e}")

    return final_data


# === MAIN ===
def main():
    driver = setup_driver()
    wait = WebDriverWait(driver, 20)

    try:
        with open(ORG_NUMBERS_FILE, 'r', encoding='utf-8') as f:
            org_numbers = [line.strip() for line in f if line.strip()]
        
        if not org_numbers:
            print(f"Файл {ORG_NUMBERS_FILE} пуст. Завершение работы.")
            return
            
        print(f"Найдено {len(org_numbers)} орг. номеров для обработки.")

        # 1. ПЕРЕХОД НА СТАРТОВУЮ СТРАНИЦУ ДЛЯ АУТЕНТИФИКАЦИИ
        driver.get("https://www.merinfo.se")
        print("\n🚦 ПАУЗА: Войдите в систему, если требуется, и нажмите ENTER здесь для старта.")
        input()

        # 2. ОБРАБОТКА КАЖДОГО НОМЕРА
        initial_count = len(org_numbers)
        for i, org_number in enumerate(list(org_numbers)): # Копируем список, чтобы безопасно изменять org_numbers
            print(f"\n=== Обработка [{i + 1}/{initial_count}]: {org_number} ===")
            search_url = f"https://www.merinfo.se/search?q={org_number}"
            time.sleep(random.uniform(1.0, 2.5)) # Задержка перед поиском
            driver.get(search_url)

            try:
                # Ищем ссылку на первую компанию в результатах
                first_result_selector = "div.result-list a[href*='/foretag/']"
                company_link_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, first_result_selector)))
                company_url = company_link_element.get_attribute("href")
                
                print(f"Найдена компания: {company_url.split('/')[-2]}")

                # Собираем данные
                data = process_company(driver, company_url)
                
                # Сохраняем и удаляем номер из списка
                if data.get('company', {}).get('name'): # Проверяем, что данные собраны
                    save_record(data, org_number, org_numbers)
                    org_numbers.remove(org_number) # Удаляем из списка в памяти
                else:
                    print(f"   [!] Данные для {org_number} не были собраны, номер не будет удален.")

                time.sleep(random.uniform(1.0, 2.5)) # Задержка после обработки

            except TimeoutException:
                print(f"   [!] Не найдено результатов для {org_number} или страница не загрузилась.")
                continue
            except Exception as e:
                print(f"   [!] Произошла ошибка при обработке {org_number}: {e}")
                continue

        print("\n🎉 Готово! Все номера обработаны.")

    except FileNotFoundError:
        print(f"🔥 Ошибка: Файл '{ORG_NUMBERS_FILE}' не найден.")
    except KeyboardInterrupt:
        print("\n🛑 Стоп.")
    except Exception as e:
        print(f"\n🔥 Произошла непредвиденная ошибка: {e}")
    finally:
        driver.quit()


if __name__ == '__main__':
    main()