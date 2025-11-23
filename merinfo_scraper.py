import re
import time
import random
import json
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementNotInteractableException,
    WebDriverException,
    StaleElementReferenceException,
)


# =====================================================
# 1. Парсинг личной страницы человека
# =====================================================
def parse_person_page(driver):
    print("    -> STEP: Parsing personal page...")
    person = {
        "name": "",
        "age": "",
        "city": "",
        "address": "",
        "phones": [],
        "vehicles": [],
        "civil_status": "",
        "url": driver.current_url,
    }

    try:
        # === Имя (красивое) ===
        try:
            person["name"] = driver.find_element(By.CSS_SELECTOR, "h1 .namn").get_attribute("textContent").strip()
            print(f"      - Name: {person['name']}")
        except:
            try:
                person["name"] = driver.find_element(By.TAG_NAME, "h1").text.strip()
                print(f"      - Name (fallback): {person['name']}")
            except:
                print("      - Name: Not found")
                pass

        # === Возраст + город (самый надёжный способ 2025) ===
        try:
            info_blocks = driver.find_elements(By.XPATH, "//h1/following-sibling::*//span[contains(@class,'text-sm')]")
            for block in info_blocks:
                txt = block.text.strip()
                # Возраст
                age_match = re.search(r"(\d+)[-–]årig|\b(\d+)\s*år\b", txt)
                if age_match:
                    person["age"] = age_match.group(1) or age_match.group(2)
                    print(f"      - Age: {person['age']}")
                # Город
                if not person["city"] and txt and "år" not in txt.lower():
                    # Иногда город в отдельном блоке с иконкой карты
                    if "Hässelby" in txt or "Stockholm" in txt or len(txt) < 30:
                        person["city"] = txt.split()[0] if txt else ""
                        print(f"      - City: {person['city']}")

            # Резерв: из title страницы
            if not person["age"] or not person["city"]:
                title = driver.title  # "Monica Andrade Hagland (Hässelby, 57 år) - Merinfo.se"
                print(f"      - Trying to get age/city from title: {title}")
                if "(" in title and ")" in title:
                    inside = title.split("(")[1].split(")")[0]
                    parts = [p.strip() for p in inside.split(",")]
                    if len(parts) >= 2:
                        if not person["city"]:
                            person["city"] = parts[0]
                            print(f"      - City (from title): {person['city']}")
                        age_match = re.search(r"\d+", parts[1])
                        if age_match and not person["age"]:
                            person["age"] = age_match.group()
                            print(f"      - Age (from title): {person['age']}")
        except:
            pass

        # === Адрес ===
        try:
            addr_elem = driver.find_element(By.XPATH, "//h3[contains(text(),'Folkbokföringsadress')]/following-sibling::address")
            person["address"] = addr_elem.text.strip().replace("\n", ", ")
            print(f"      - Address: {person['address']}")
        except:
            # иногда просто в <address> без h3
            try:
                person["address"] = driver.find_element(By.TAG_NAME, "address").text.strip().replace("\n", ", ")
                print(f"      - Address (fallback): {person['address']}")
            except:
                print("      - Address: Not found")
                pass

        # === Телефоны ===
        try:
            rows = driver.find_elements(By.XPATH, "//table[.//th[contains(text(),'Telefonnummer')]]//tbody/tr")
            for row in rows:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) >= 2:
                    num = cols[0].text.strip()
                    user = cols[1].text.strip()
                    if num and num != "-":
                        person["phones"].append({"number": num, "user": user})
            print(f"      - Phones found: {len(person['phones'])}")
        except:
            print("      - Phones: Not found")
            pass

        # === Машины (включая машины других жильцов по адресу) ===
        try:
            # Основной блок с машинами
            vehicle_rows = driver.find_elements(By.XPATH, "//div[@id='vehicle-summary']//table//tr | //table[.//th[contains(text(),'Märke och modell')]]//tbody/tr")
            for row in vehicle_rows:
                cells = row.find_elements(By.TAG_NAME, "td")
                if cells:
                    txt = cells[0].text.strip()
                    if txt and len(txt) > 3:
                        person["vehicles"].append(txt)
            print(f"      - Vehicles found: {len(person['vehicles'])}")
        except:
            print("      - Vehicles: Not found")
            pass

        # === Семейное положение ===
        try:
            status_text = driver.find_element(By.XPATH, "//h3[contains(text(),'Civilstatus')]/following-sibling::*//text()")
            person["civil_status"] = status_text.get_attribute("textContent").strip()
            print(f"      - Civil status: {person['civil_status']}")
        except:
            try:
                # иногда просто текст "gift", "skild" и т.д.
                civil = driver.find_element(By.XPATH, "//h3[contains(text(),'Civilstatus')]/following::text()[contains(., 'gift') or contains(., 'skild') or contains(., 'sambo') or contains(., 'ensamstående')]")
                person["civil_status"] = civil.text.strip()
                print(f"      - Civil status (fallback): {person['civil_status']}")
            except:
                print("      - Civil status: Not found")
                pass

    except Exception as e:
        print(f"    → Ошибка парсинга страницы: {e}")

    print(f"    -> RESULT: {person}")
    return person
# =====================================================
# 2. Парсинг правления
# =====================================================
def parse_board_page(driver):
    print("  -> STEP: Parsing board page...")
    # КРИТИЧНО: растягиваем окно, чтобы увидеть десктопные колонки (lg:table-cell)
    driver.set_window_size(1440, 900)
    time.sleep(1)  # даем время на перерисовку

    members = []
    seen_names = set()  # защита от дублей

    try:
        print("    - Waiting for board table...")
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.XPATH, "//table[.//th[contains(text(),'Senaste förändring')]]"))
        )
        time.sleep(2)
        print("    - Board table found.")

        tables = driver.find_elements(By.XPATH, "//table[.//th[contains(text(),'Senaste förändring')]]")
        print(f"    - Found {len(tables)} board table(s).")

        for table in tables:
            rows = table.find_elements(By.XPATH, ".//tbody/tr")
            print(f"    - Processing {len(rows)} rows in a table.")
            for row in rows:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) == 0:
                    continue

                # Первая колонка — всегда содержит имя
                name_cell = cols[0]
                name_link = name_cell.find_elements(By.TAG_NAME, "a")
                profile_url = name_link[0].get_attribute("href") if name_link else ""

                # Ищем имя — либо в <a>, либо в span
                name_elem = name_cell.find_element(By.XPATH, ".//a | .//span[not(contains(@class,'inline-block'))]")
                full_name = name_elem.text.strip()

                if full_name in seen_names:
                    print(f"    - Skipping duplicate name: {full_name}")
                    continue
                seen_names.add(full_name)

                age = ""
                city = ""
                roles = ""
                appointed_date = ""

                # === ДЕСКТОПНАЯ ВЕРСИЯ (lg:table-cell) ===
                if len(cols) >= 5:
                    try:
                        age = cols[1].text.strip().replace("år", "").strip()
                        city = cols[2].text.strip()
                        roles = cols[-2].text.strip()  # предпоследняя колонка
                        appointed_date = cols[-1].text.strip()
                    except:
                        pass
                else:
                    # === МОБИЛЬНАЯ ВЕРСИЯ (если вдруг не растянули окно) ===
                    lines = [line.strip() for line in name_cell.text.split("\n") if line.strip()]
                    for line in lines:
                        if "år" in line and not age:
                            age = line.replace("år", "").replace("-", "").strip()
                        elif line.startswith("- ") and not city:
                            city = line.replace("-", "").strip()

                    # Роли и дата — из <dl> в мобильной версии
                    try:
                        dl = name_cell.find_element(By.TAG_NAME, "dl")
                        dd_texts = [dd.text.strip() for dd in dl.find_elements(By.TAG_NAME, "dd")]
                        for text in dd_texts:
                            if "Verkställande" in text or "Styrelsesuppleant" in text:
                                roles = text
                            elif "Senaste förändring" in text:
                                appointed_date = text.split(":")[-1].strip()
                    except:
                        pass

                member = {
                    "name": full_name,
                    "age": age,
                    "city": city,
                    "roles": roles,
                    "appointed_date": appointed_date,
                    "profile_url": profile_url or "",
                    "personal_data": None
                }
                print(f"      - Parsed member: {full_name}")
                members.append(member)

    except Exception as e:
        print(f"  → Ошибка парсинга правления: {e}")

    print(f"  -> RESULT: Found {len(members)} board members.")
    return members
# =====================================================
# 3. Парсинг телефонов компании
# =====================================================
def parse_phone_page(driver):
    print("  -> STEP: Parsing phone page...")
    phones = []
    try:
        print("    - Waiting for phone table...")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//table[.//th[contains(text(),'Telefonnummer')]]"))
        )
        time.sleep(2)
        print("    - Phone table found.")

        rows = driver.find_elements(
            By.XPATH, "//table[.//th[contains(text(),'Telefonnummer')]]//tbody/tr"
        )
        print(f"    - Found {len(rows)} rows in phone table.")
        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) < 6:
                continue
            phone_data = {
                "number": cols[0].text.strip(),
                "user": cols[1].text.strip(),
                "operator": cols[2].text.strip(),
                "last_ported": cols[3].text.strip(),
                "previous_operator": cols[4].text.strip(),
                "type": cols[5].text.strip(),
            }
            phones.append(phone_data)
            print(f"      - Parsed phone: {phone_data['number']}")
    except Exception as e:
        print(f"    - Could not parse phone page: {e}")
        pass
    print(f"  -> RESULT: Found {len(phones)} phones.")
    return phones


# =====================================================
# 4. Поиск Bankgironummer (ИСПРАВЛЕНО)
# =====================================================
def check_bankgiro(driver, org_num):
    """
    Теперь функция работает в ТОМ ЖЕ окне, чтобы избежать 'invalid session id'.
    """
    print("  -> STEP: Checking Bankgiro...")
    bankgiro = None

    try:
        search_url = f"https://www.bankgirot.se/sok-bankgironummer?bgnr=&company=&city=&orgnr={org_num.replace('-', '')}"
        print(f"    - Navigating to: {search_url}")

        # Просто переходим по ссылке в текущем окне
        driver.get(search_url)

        # Ждем загрузки результатов
        print("    - Waiting for Bankgiro results...")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ol.bgnr-results, div#bg-info, body"))
        )
        time.sleep(random.uniform(1.5, 2.5))

        # Ищем результат
        try:
            bankgiro_element = driver.find_element(
                By.XPATH, "//li[contains(text(), 'Bankgironummer')]/following-sibling::li"
            )
            bankgiro = bankgiro_element.text.strip()
            if bankgiro:
                print(f"  → Bankgironummer найден: {bankgiro}")
            else:
                print("  → Bankgironummer НЕ найден (пустой элемент)")
                bankgiro = None
        except NoSuchElementException:
            print("  → Bankgironummer НЕ найден (нет элемента)")

    except Exception as e:
        print(f"  → Ошибка на bankgirot.se: {e}")

    # Мы НЕ закрываем вкладку и НЕ переключаем хендлы.
    # Скрипт просто вернется в основной цикл и там сделает driver.get(merinfo)
    print(f"  -> RESULT: Bankgiro is '{bankgiro}'")
    return bankgiro


# =====================================================
# 5. Основной парсер карточки компании
# =====================================================
def parse_company_page(driver, org_num):
    print("  -> STEP: Parsing main company page...")
    data = {
        "org_number": org_num,
        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "url": driver.current_url,
        "name": "",
        "phone": "",
        "address": "",
        "description": "",
        "signatory_rules": "",
        "status": "",
        "registered_date": "",
        "f_skatt": "",
        "vat_registered": "",
        "company_form": "",
        "county": "",
        "municipality": "",
        "sni_codes": [],
        "industry": "",
        "financials": {},       # ← из большой таблицы (все года) — ТЕПЕРЬ РАБОТАЕТ!
        "key_figures": {},      # ← из правого блока (резервный)
        "all_phones": [],
        "board_members": [],
        "bankgiro": None,
    }

    # === 1. Медленная прокрутка с шагом 0.5 сек — 100% подгрузка ===
    print("  → Медленная прокрутка страницы для подгрузки всех блоков...")
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.5)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
    time.sleep(3)
    print("  → Прокрутка завершена.")

    # === 2. Основные данные ===
    print("  → Parsing main company data...")
    try:
        data["name"] = driver.find_element(By.CSS_SELECTOR, "h1 .namn").text.strip()
        print(f"    - Name: {data['name']}")
    except: pass

    try:
        data["phone"] = driver.find_element(By.XPATH, "//a[contains(@href,'tel:')]").text.strip()
        print(f"    - Phone: {data['phone']}")
    except: pass

    try:
        addr = driver.find_element(By.XPATH, "//section[.//h3[contains(text(),'Adress')]]//address").text.strip()
        data["address"] = addr.replace("\n", ", ")
        print(f"    - Address: {data['address']}")
    except: pass

    # === 3. Verksamhet & status ===
    print("  → Parsing 'Verksamhet & status'...")
    try:
        section = driver.find_element(By.ID, "sammanfattning")
        text = section.text

        if "Verksamhetsbeskrivning" in text:
            data["description"] = text.split("Verksamhetsbeskrivning")[1].split("Firmatecknare")[0].strip()
            print(f"    - Description: Found")

        if "Firmatecknare" in text:
            data["signatory_rules"] = text.split("Firmatecknare")[1].split("Status:")[0].strip()
            print(f"    - Signatory Rules: Found")

        for line in text.split("\n"):
            if ":" not in line: continue
            key, val = line.split(":", 1)
            key = key.strip().lower()
            val = val.strip()
            if "status" in key: data["status"] = val
            elif "registrerat" in key: data["registered_date"] = val
            elif "f-skatt" in key: data["f_skatt"] = val
            elif "momsregistrerad" in key: data["vat_registered"] = val
            elif "bolagsform" in key: data["company_form"] = val
            elif "länssäte" in key: data["county"] = val
            elif "kommunsäte" in key: data["municipality"] = val
        print(f"    - Status: {data['status']}, Registered: {data['registered_date']}, F-skatt: {data['f_skatt']}")

        if "Svensk näringsgrensindelning:" in text:
            sni_part = text.split("Svensk näringsgrensindelning:")[1]
            block = sni_part.split("Bransch:")[0] if "Bransch:" in sni_part else sni_part
            data["sni_codes"] = [x.strip() for x in block.split("\n") if x.strip() and "-" in x]
            print(f"    - SNI Codes: {len(data['sni_codes'])} found")

        # === Bransch: полная иерархия ===
        try:
            bransch_block = driver.find_element(By.XPATH, "//h3[contains(text(),'Bransch:')]/following-sibling::div")

            main_category = ""
            sub_category = ""

            try:
                main_a = bransch_block.find_element(By.XPATH, ".//a[not(./ul)]")
                main_category = main_a.text.strip()
            except:
                pass

            try:
                sub_a = bransch_block.find_element(By.XPATH, ".//ul//a")
                sub_category = sub_a.text.strip()
            except:
                pass

            if main_category and sub_category:
                data["industry"] = f"{main_category} > {sub_category}"
            elif main_category:
                data["industry"] = main_category
            elif sub_category:
                data["industry"] = sub_category

            print(f"  → Bransch: {data['industry']}")

        except Exception as e:
            print(f"  → Не удалось собрать Bransch: {e}")

    except Exception as e:
        print(f"  → Ошибка парсинга Verksamhet: {e}")

    # === 4. БОЛЬШАЯ ФИНАНСОВАЯ ТАБЛИЦА (все года) — ТЕПЕРЬ ТОЧНО РАБОТАЕТ! ===
    print("  → Ищу большую финансовую таблицу...")
    try:
        # Ждём именно эту таблицу — она всегда имеет класс table-hide-last-cols
        table = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//table[contains(@class,'table-hide-last-cols')]"))
        )
        print("  → Таблица найдена!")

        # Заголовки (годы)
        headers = [th.text.strip() for th in table.find_elements(By.TAG_NAME, "th")]
        rows = table.find_elements(By.TAG_NAME, "tr")

        year_cols = {}
        for idx, header in enumerate(headers):
            if re.match(r"\d{4}-\d{2}", header):
                year_cols[idx] = header

        print(f"  → Найдено лет: {list(year_cols.values())}")

        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if not cells: continue
            label_cell = row.find_element(By.XPATH, ".//td[1] | .//th[1]")
            label = label_cell.text.strip()
            if not label: continue

            for col_idx, year in year_cols.items():
                if col_idx < len(cells):
                    value = cells[col_idx].text.strip()
                    if value:
                        if year not in data["financials"]:
                            data["financials"][year] = {}
                        data["financials"][year][label] = value

        print(f"  → Собрано финансов за {len(data['financials'])} лет(а)")

    except TimeoutException:
        print("  → Большая таблица НЕ найдена")
    except Exception as e:
        print(f"  → Ошибка при парсинге таблицы: {e}")

    # === 5. Правый блок "Nyckeltal 2023-08" (резервный) ===
    print("  → Parsing 'Nyckeltal' block...")
    try:
        key_block = driver.find_element(By.XPATH, "//h3[contains(text(),'Nyckeltal')]/following-sibling::div")
        year_header = driver.find_element(By.XPATH, "//h3[contains(text(),'Nyckeltal')]").text.strip()
        year = year_header.replace("Nyckeltal ", "").strip()
        print(f"    - Key figures for year: {year}")

        data["key_figures"][year] = {}
        lines = key_block.find_elements(By.XPATH, ".//div[contains(@class,'flex') and contains(@class,'justify-between')]")
        for line in lines:
            spans = line.find_elements(By.TAG_NAME, "span")
            if len(spans) >= 2:
                label = spans[0].text.strip()
                value = spans[1].text.strip()
                data["key_figures"][year][label] = value
        print(f"    - Found {len(data['key_figures'][year])} key figures.")

    except Exception as e:
        print(f"  → Не удалось собрать правый блок: {e}")

    print("  -> RESULT: Finished parsing company page.")
    return data
# =====================================================
# ИНИЦИАЛИЗАЦИЯ ДРАЙВЕРА (Вынесена отдельно)
# =====================================================
def init_driver():
    print("Initializing Chrome driver...")
    options = uc.ChromeOptions()
    options.debugger_address = "127.0.0.1:9222"  # Можно раскомментировать, если используете ручной запуск Chrome
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Добавляем для стабильности:
    options.add_argument("--disable-popup-blocking")

    # use_subprocess=True иногда вызывает проблемы на Mac/Linux, если не работает - уберите
    driver = uc.Chrome(options=options, use_subprocess=True)
    driver.set_page_load_timeout(60)  # Таймаут загрузки страницы
    print("Driver initialized.")
    return driver


# =====================================================
# ГЛАВНЫЙ ЦИКЛ
# =====================================================
def start_app():
    print("Merinfo + Bankgirot → Полный парсер 2025 (ФИНАЛЬНАЯ ВЕРСИЯ — 100% фильтр anmärkningar)")

    # 1. Загрузка списка
    try:
        with open("org_numbers_bil.txt", "r", encoding="utf-8") as f:
            org_numbers = [line.strip() for line in f if line.strip()]
        print(f"Загружено {len(org_numbers)} компаний")
    except FileNotFoundError:
        print("Файл org_numbers_bil.txt не найден!")
        return

    output_file = "merinfo_bankgiro_full.jsonl"
    print(f"Output will be saved to {output_file}")

    # 2. Запуск драйвера
    driver = init_driver()

    # Принятие куки (единоразово)
    try:
        print("Navigating to merinfo.se to accept cookies...")
        driver.get("https://www.merinfo.se")
        time.sleep(3)
        try:
            driver.find_element(By.ID, "onetrust-accept-btn-handler").click()
            print("Куки приняты")
        except:
            print("Cookie banner not found or already accepted.")
            pass
    except Exception as e:
        print(f"Ошибка при старте: {e}")

    # 3. Цикл по компаниям
    for i, org_num in enumerate(org_numbers):
        print(f"\n[{i + 1}/{len(org_numbers)}] Проверяю: {org_num}")

        # --- Блок восстановления сессии ---
        if driver is None:
            print("Пересоздание драйвера после краша...")
            try:
                driver = init_driver()
            except Exception as e:
                print(f"Не удалось пересоздать драйвер: {e}")
                time.sleep(10)
                continue

        try:
            print(f"  - Searching for {org_num}...")
            driver.get(f"https://www.merinfo.se/search?q={org_num}")
            time.sleep(3)

            # Проверка куки (на всякий случай)
            try:
                cookie_btn = driver.find_elements(By.ID, "onetrust-accept-btn-handler")
                if cookie_btn:
                    cookie_btn[0].click()
                    time.sleep(1)
            except:
                pass

            # Ждём загрузки страницы
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            print("  - Search page loaded.")

            # Находим карточку компании по номеру
            # === НАХОДИМ ПЕРВУЮ (ГЛАВНУЮ) КАРТОЧКУ КОМПАНИИ ===
            try:
                print("  - Looking for company card...")
                card = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.XPATH,
                         "(//div[contains(@class, 'mi-relative') and contains(@class, 'mi-bg-white') and .//h2/a[contains(@href, '/foretag/')]])[1]")
                    )
                )
                print("  - Company card found.")
            except TimeoutException:
                print(f"НЕ НАЙДЕНА карточка для {org_num}")
                continue

            # Проверка на anmärkningar
            try:
                card.find_element(By.XPATH,
                                  ".//span[contains(@class, 'mi-text-red') and contains(text(), 'Det finns något att anmärka på')]")
                print(f"ОТКЛОНЕНО {org_num} — есть anmärkningar")
                continue
            except NoSuchElementException:
                print(f"ПРОШЛО {org_num} — чистая компания")

            # Получаем ссылку
            try:
                profile_url = card.find_element(By.XPATH, ".//h2/a").get_attribute("href")
            except:
                print(f"Нет ссылки на профиль для {org_num}")
                continue

            print(f"Переходим в профиль: {profile_url}")

            # 1. Основная карточка
            driver.get(profile_url)
            time.sleep(3)
            result = parse_company_page(driver, org_num)

            # 2. Телефоны
            phones_url = profile_url.rstrip("/") + "/telefonnummer"
            print(f"  - Navigating to phones page: {phones_url}")
            driver.get(phones_url)
            time.sleep(3)
            result["all_phones"] = parse_phone_page(driver)

            # 3. Правление
            board_url = profile_url.rstrip("/") + "/styrelse-koncern"
            print(f"  - Navigating to board page: {board_url}")
            driver.get(board_url)
            time.sleep(3)
            result["board_members"] = parse_board_page(driver)

            # 4. Личные страницы участников правления
            print("  - Parsing personal pages for board members...")
            for member in result["board_members"]:
                if member.get("profile_url"):
                    print(f"    - Navigating to personal page: {member['profile_url']}")
                    driver.get(member["profile_url"])
                    time.sleep(3)
                    member["personal_data"] = parse_person_page(driver)
                else:
                    print(f"    - No profile URL for member: {member['name']}")

            # 5. Bankgiro
            result["bankgiro"] = check_bankgiro(driver, org_num)

            # Сохранение результата
            print(f"  - Saving result for {org_num} to {output_file}")
            with open(output_file, "a", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
                f.write("\n")

            print(f"ГОТОВО! Телефонов: {len(result.get('all_phones', []))}, "
                  f"Участников: {len(result.get('board_members', []))}, "
                  f"Bankgiro: {result['bankgiro'] or '—'}")

        except (WebDriverException, ConnectionError) as e:
            print(f"КРИТИЧЕСКАЯ ОШИБКА БРАУЗЕРА с {org_num}: {e}")
            print("Перезапускаем браузер...")
            try:
                driver.quit()
            except:
                pass
            driver = None

        except Exception as e:
            print(f"Неизвестная ошибка при обработке {org_num}: {e}")

        # Рандомная задержка между запросами
        delay = random.uniform(5.0, 9.0)
        print(f"  - Waiting for {delay:.1f} seconds...")
        time.sleep(delay)

    print(f"\nПарсинг завершён! Все чистые компании сохранены в {output_file}")
    if driver:
        try:
            driver.quit()
        except:
            pass


if __name__ == "__main__":
    start_app()
