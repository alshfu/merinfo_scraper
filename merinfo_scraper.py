#!/usr/bin/env python3
"""
Merinfo Deep Board Parser v3 (исправленная версия)
"""

import re
import time
import random
import json
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

import certifi
from pymongo import MongoClient
from bson import ObjectId  # нужно для очистки

# ==================== НАСТРОЙКИ ====================
MONGO_URI = 'mongodb+srv://alshfu86:as785ghqw590!Q@cluster0.hm5obgl.mongodb.net/?appName=Cluster0'
DB_NAME = 'merinfo_db'
COLLECTION_NAME = 'companies_deep'

INPUT_FILE = Path("org_numbers_kläder.txt")
BACKUP_DIR = Path("backup_board")
BACKUP_DIR.mkdir(exist_ok=True)

DELAY_MIN = 6.0
DELAY_MAX = 12.0


# ===================================================


def get_delay():
    return random.uniform(DELAY_MIN, DELAY_MAX)


def is_cloudflare(html: str) -> bool:
    return any(x in html.lower() for x in ["utför säkerhetsverifiering", "cf-turnstile-response"])


def safe_get(driver, url: str, max_attempts: int = 3) -> bool:
    for attempt in range(max_attempts):
        try:
            driver.get(url)
            time.sleep(get_delay() + 1.5)
            if is_cloudflare(driver.page_source):
                print("    [!] Cloudflare → ждём и refresh")
                time.sleep(random.uniform(10, 16))
                driver.refresh()
                time.sleep(get_delay() + 2)
                if is_cloudflare(driver.page_source):
                    return False
            return True
        except Exception:
            time.sleep(8)
    return False


def clean_for_json(obj):
    """Рекурсивно очищает dict от ObjectId и других несериализуемых типов"""
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_for_json(item) for item in obj]
    elif isinstance(obj, ObjectId):
        return str(obj)
    else:
        return obj


# ==================== ПАРСИНГ ЧЕЛОВЕКА ====================
def parse_person_page(driver, url: str):
    if not safe_get(driver, url):
        return None

    print(f"    → Парсим человека: {url.split('/')[-1]}")

    person = {
        "name": "", "age": "", "city": "", "address": "",
        "civil_status": "", "phones": [], "vehicles": [],
        "companies": [], "url": url,
        "scraped_at": datetime.now().isoformat()
    }

    try:
        person["name"] = driver.find_element(By.CSS_SELECTOR, "h1 .namn").text.strip()
    except:
        try:
            person["name"] = driver.find_element(By.TAG_NAME, "h1").text.strip()
        except:
            pass

    try:
        age_el = driver.find_element(By.XPATH, "//span[contains(text(),'årig') or contains(text(),' år')]")
        m = re.search(r"(\d+)", age_el.text)
        if m:
            person["age"] = m.group(1)
    except:
        pass

    try:
        person["city"] = driver.find_element(By.XPATH, "//div[@dusk='summery-city']//span").text.strip()
    except:
        pass

    try:
        addr = driver.find_element(By.XPATH, "//h3[contains(text(),'Folkbokföringsadress')]/following-sibling::address")
        person["address"] = addr.text.strip().replace("\n", ", ")
    except:
        pass

    try:
        for row in driver.find_elements(By.XPATH, "//table[.//th[contains(text(),'Telefonnummer')]]//tbody/tr"):
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) >= 2 and cols[0].text.strip() not in ["", "-"]:
                person["phones"].append({
                    "number": cols[0].text.strip(),
                    "user": cols[1].text.strip()
                })
    except:
        pass

    try:
        for a in driver.find_elements(By.CSS_SELECTOR, "#bolagsengagemang a[href*='/foretag/']"):
            person["companies"].append({
                "name": a.text.strip(),
                "url": a.get_attribute("href")
            })
    except:
        pass

    return person


# ==================== ПАРСИНГ ПРАВЛЕНИЯ (УЛУЧШЕННАЯ ВЕРСИЯ) ====================
def parse_board_page(driver, company_url: str):
    board_url = company_url.rstrip("/") + "/styrelse-koncern"
    print(f"  → Переходим на страницу правления...")

    if not safe_get(driver, board_url):
        return []

    members = []

    try:
        # Ждём появления заголовка "Styrelsemedlemmar" или таблицы
        WebDriverWait(driver, 20).until(
            EC.any_of(
                EC.presence_of_element_located((By.XPATH, "//h3[contains(text(),'Styrelsemedlemmar')]")),
                EC.presence_of_element_located((By.XPATH, "//table"))
            )
        )
        time.sleep(2)

        # Пробуем найти строки правления (новая структура Merinfo)
        rows = driver.find_elements(By.XPATH, "//div[contains(@class,'lg:grid') and contains(@class,'grid-cols')]")

        if not rows:
            # fallback — старый вариант с таблицами
            rows = driver.find_elements(By.XPATH, "//table[.//th[contains(text(),'Senaste')]]//tbody/tr")

        for row in rows:
            try:
                # Имя + ссылка
                name_link = row.find_element(By.XPATH, ".//a[contains(@href,'/person/')]")
                name = name_link.text.strip()
                profile_url = name_link.get_attribute("href")

                # Возраст, город, должность
                text = row.text
                age_match = re.search(r"(\d+)\s*år", text)
                age = age_match.group(1) if age_match else ""

                # Город (обычно после возраста)
                city_match = re.search(r"(\d+)\s*år\s*·\s*([A-Za-zåäöÅÄÖ]+)", text)
                city = city_match.group(2) if city_match else ""

                # Должность
                role = ""
                if "Ordförande" in text:
                    role = "Ordförande, Styrelseledamot"
                elif "Styrelseledamot" in text:
                    role = "Styrelseledamot"
                elif "Styrelsesuppleant" in text:
                    role = "Styrelsesuppleant"

                members.append({
                    "name": name,
                    "age": age,
                    "city": city,
                    "role": role,
                    "profile_url": profile_url,
                    "personal_data": None
                })
            except:
                continue

    except Exception as e:
        print(f"  → Ошибка парсинга правления: {e}")

    print(f"  → Найдено членов правления: {len(members)}")
    return members


# ==================== ГЛАВНЫЙ ЦИКЛ ====================
def main():
    print("=== Merinfo Deep Board Parser v3 ===")

    try:
        client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
        collection = client[DB_NAME][COLLECTION_NAME]
        print("✅ MongoDB подключена")
    except Exception as e:
        print(f"❌ MongoDB ошибка: {e}")
        return

    if not INPUT_FILE.exists():
        print(f"❌ Файл не найден: {INPUT_FILE}")
        return

    org_numbers = [line.strip() for line in INPUT_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]

    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(90)

    for i, org_num in enumerate(org_numbers):
        print(f"\n[{i + 1}/{len(org_numbers)}] {org_num}")

        if collection.find_one({"org_number": org_num}):
            print("⏭ Уже в базе")
            continue

        try:
            if not safe_get(driver, f"https://www.merinfo.se/search?q={org_num}"):
                continue

            if "Det finns något att anmärka på" in driver.page_source:
                print("    [!] Пропускаем — есть замечание")
                continue

            try:
                link = WebDriverWait(driver, 12).until(
                    EC.presence_of_element_located((By.XPATH, "//h2/a[contains(@href, '/foretag/')]"))
                )
                company_url = link.get_attribute("href")
            except TimeoutException:
                print("    НЕ НАЙДЕНА карточка компании")
                continue

            if not safe_get(driver, company_url):
                continue

            company_data = {
                "org_number": org_num,
                "company_url": company_url,
                "name": "",
                "scraped_at": datetime.now().isoformat(),
                "board_members": []
            }

            try:
                company_data["name"] = driver.find_element(By.CSS_SELECTOR, "h1 .namn").text.strip()
            except:
                pass

            # === Парсим правление ===
            board_members = parse_board_page(driver, company_url)

            for member in board_members:
                if member.get("profile_url"):
                    member["personal_data"] = parse_person_page(driver, member["profile_url"])
                    time.sleep(get_delay())

            company_data["board_members"] = board_members

            # Сохраняем в MongoDB
            collection.insert_one(company_data)

            # Сохраняем чистый JSON (без ObjectId)
            clean_data = clean_for_json(company_data)
            with open(BACKUP_DIR / f"{org_num}.json", "w", encoding="utf-8") as f:
                json.dump(clean_data, f, ensure_ascii=False, indent=2)

            print(f"✅ Сохранено: {org_num} | Членов правления: {len(board_members)}")

        except Exception as e:
            print(f"❌ Ошибка на {org_num}: {e}")

        time.sleep(random.uniform(8, 14))

    print("\nГотово!")
    client.close()
    try:
        driver.quit()
    except:
        pass


if __name__ == "__main__":
    main()