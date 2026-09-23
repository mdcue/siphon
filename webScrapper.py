from bs4 import BeautifulSoup
import requests
import logging
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
    )
logger = logging.getLogger(__name__)

def table_scraping(url):
    page = requests.get(url,headers = {"User-Agent":"Mozilla/5.0"})
    page.raise_for_status()
    
    soup = BeautifulSoup(page.text, "html.parser")
    tables = soup.find_all("table")

    if not tables:
        raise ValueError("No tables found.")
    
    data = []
    
    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue
        
        headers = [
            cell.get_text("", strip=True)
            for cell in rows[0].find_all(["th","td"])]
        
        table_data = []
        
        for row in rows[1:]:
            cells = row.find_all(["td","th"])
            values = [cell.get_text("", strip = True)
                    for cell in cells]
            if len(values) == len(headers):
                table_data.append(values)
        
        if headers:
            table_df = pd.DataFrame(table_data, columns = headers)
            data.append(table_df)
    return data

def clean_dataframe(df):
    df = df.copy()
    for col in df.columns:
        sample = df[col].astype(str).str.strip()
        
        if sample.str.contains(r"^\$", regex = True).any():
            df[col] = (
                sample.str.replace(r"\$", "", regex = True)
                .str.replace(" B", "e9", regex = False)
                .str.replace(" M", "e6", regex = False)
                .str.replace(" K", "e3", regex = False)
                .apply(pd.to_numeric, errors = "coerce")
            )
        elif sample.str.contains(r"%$", regex = True).any():
            df[col] = (
                sample.str.replace(r"%","",regex = False)
                .apply(pd.to_numeric, errors = "coerce")
            )
    
    return df
