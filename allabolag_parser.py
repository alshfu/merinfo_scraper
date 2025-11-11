import time
import random
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager

# === КОНФИГУРАЦИЯ ===
OUTPUT_FILE = "org_numbers.txt"
MAX_PAGES = 500


# === НАСТРОЙКА DRIVER ===
def setup_driver():
    options = Options()

    # --- Проблема с расширением ---
    # Загрузка расширения по абсолютному пути -- очень ненадежный метод.
    # Версия в пути (3.50.6_0) может измениться, и тогда все сломается.
    # Лучше установить расширение в отдельный профиль Chrome и использовать его.
    # Пока что этот код закомментирован, чтобы не вызывать ошибок.
    #
    # EXTENSION_PATH = "/Users/al_sh/Library/Application Support/Google/Chrome/Default/Extensions/nbcojefnccbanplpoffopkoepjmhgdgh/3.50.6_0"
    # options.add_argument(f"--load-extension={EXTENSION_PATH}")

    # Остальные настройки
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.page_load_strategy = 'eager'

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver


def save_org_nr_to_file(org_nr):
    """Добавляет орг. номер в файл."""
    try:
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            f.write(org_nr + "\n")
        print(f"   [SAVE] {org_nr}")
    except Exception as e:
        print(f"   [ERROR] Не удалось сохранить: {e}")


def slow_scroll_to_bottom(driver):
    """Плавная прокрутка страницы вниз для подгрузки элементов."""
    print("   📉 Прокрутка страницы вниз...")
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollBy(0, 800);")
        time.sleep(random.uniform(0.5, 1.0))
        new_height = driver.execute_script("return document.body.scrollHeight")
        current_scroll = driver.execute_script("return window.pageYOffset + window.innerHeight")
        if current_scroll >= new_height:
            break
        last_height = new_height
    time.sleep(1)


# === ГЛАВНЫЙ ЦИКЛ ===
def main():
    driver = setup_driver()
    wait = WebDriverWait(driver, 15)

    try:
        driver.get("https://www.allabolag.se/segmentering")

        # --- Улучшенная пауза ---
        # Пауза реализована с помощью функции input().
        # Скрипт остановится на этой строке и будет ждать, пока вы не нажмете Enter в консоли.
        print("\n" + "="*60)
        print("🚦 СКРИПТ НА ПАУЗЕ")
        print("   1. Настройте фильтры на сайте Allabolag в открывшемся окне Chrome.")
        print("   2. Дождитесь, когда появится список компаний.")
        print("   3. Вернитесь в эту консоль и нажмите ENTER, чтобы начать сбор данных.")
        print("="*60 + "\n")
        input(">>> Нажмите ENTER для продолжения <<<")
        print("\n🚀 Пауза снята, начинаю работу...")


        page_counter = 0
        while page_counter < MAX_PAGES:
            page_counter += 1
            print(f"\n=== Обработка страницы {page_counter} ===")

            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.SegmentationSearchResultCard-card")))
            except TimeoutException:
                print("🛑 Карточки не найдены (возможно, конец списка).")
                break

            slow_scroll_to_bottom(driver)

            cards = driver.find_elements(By.CSS_SELECTOR, "div.SegmentationSearchResultCard-card")
            print(f"Найдено карточек на странице: {len(cards)}")

            for card in cards:
                try:
                    # 1. Проверка на Ликвидатора
                    is_liquidated = False
                    try:
                        if card.find_elements(By.XPATH,
                                              ".//div[contains(@class, 'CardHeader-propertyHeader') and text()='Likvidator']"):
                            is_liquidated = True
                    except:
                        pass

                    if not is_liquidated:
                        # 2. Извлечение Org.nr
                        # Ищем span, который содержит текст 'Org.nr'
                        org_element = card.find_element(By.XPATH,
                                                        ".//span[contains(@class, 'CardHeader-propertyList') and contains(., 'Org.nr')]")
                        raw_text = org_element.text

                        # Используем регулярное выражение для поиска формата XXXXXX-XXXX
                        match = re.search(r"(\d{6}-\d{4})", raw_text)
                        if match:
                            org_nr = match.group(1)
                            save_org_nr_to_file(org_nr)
                        else:
                            # Если вдруг формат отличается (редко, но бывает)
                            print(f"   [WARN] Не удалось извлечь Org.nr из: {raw_text}")

                except StaleElementReferenceException:
                    continue
                except NoSuchElementException:
                    # Если у карточки нет Org.nr (странно, но возможно)
                    continue
                except Exception as e:
                    print(f"   [ERROR] Ошибка карточки: {e}")
                    continue

            # Пагинация
            try:
                next_button = driver.find_element(By.CSS_SELECTOR, "a[aria-label='Go to next page']")
                if "Mui-disabled" in next_button.get_attribute("class"):
                    print("\n🏁 Достигнута последняя страница.")
                    break
                print("➡ Переход на следующую страницу...")
                driver.execute_script("arguments[0].click();", next_button)
                time.sleep(random.uniform(3.0, 5.0))
            except NoSuchElementException:
                print("\n🏁 Кнопка 'Nästa' не найдена. Конец списка.")
                break

    except KeyboardInterrupt:
        print("\n🛑 Скрипт остановлен.")
    finally:
        driver.quit()


if __name__ == '__main__':
    main()