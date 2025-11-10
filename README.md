# Swedish Company Scraper

This project is a web scraper for gathering information about Swedish companies from the `allabolag.se` and `merinfo.se` websites. It consists of two main Python scripts that use the Selenium library to automate the process of data extraction.

## Features

-   Scrapes company organization numbers from `allabolag.se`.
-   Scrapes detailed company information from `merinfo.se`, including:
    -   Company details (name, legal form, status, registration date)
    -   Contact information (address, phone number, municipality, county)
    -   Tax information (F-Skatt, VAT registration, employer registration)
    -   Financial data (revenue, profit, total assets)
    -   Industry information (SNI code, categories, activity description)
    -   Board member details (name, age, role, address)
-   Saves the scraped data in a JSONL file for easy processing.
-   Handles pagination and avoids duplicate entries.

## How It Works

The project is divided into two main scripts:

1.  **`allabolag_parser.py`**: This script is used to gather a list of company organization numbers from `allabolag.se`. It opens the website and allows the user to manually apply search filters. Once the filters are set, the script automatically scrapes the organization numbers from the search results and saves them to `org_numbers.txt`.

2.  **`main.py`**: This script reads the organization numbers from `org_numbers.txt` and, for each number, it navigates to `merinfo.se` to scrape detailed information about the company. The scraped data is then saved in a JSONL file named `merinfo_complete_assistants.jsonl`.

## Requirements

-   Python 3.x
-   Selenium
-   webdriver-manager

## Usage

1.  Install the required Python libraries:
    ```
    pip install selenium webdriver-manager
    ```
2.  Run the `allabolag_parser.py` script to gather organization numbers:
    ```
    python allabolag_parser.py
    ```
    The script will open a browser window. Apply your desired filters on the `allabolag.se` website and then press Enter in the console to start scraping. The organization numbers will be saved in `org_numbers.txt`.

3.  Run the `main.py` script to scrape the detailed company information:
    ```
    python main.py
    ```
    The script will read the organization numbers from `org_numbers.txt`, scrape the data from `merinfo.se`, and save the results in `merinfo_complete_assistants.jsonl`.
