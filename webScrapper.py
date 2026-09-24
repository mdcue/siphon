from bs4 import BeautifulSoup
import requests
import logging
import pandas as pd

#logger is used to log messages for debugging and monitoring purposes.
#It provides a way to track the flow of the program and capture important events or errors that occur during execution.
#A better alternative to using plain print() statements to identify issues in the code.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
    )
logger = logging.getLogger(__name__)

#The main function, to extract/fetch the page
#Also, the use of  "User-Agent" header is to avoid being blocked by some websites that restrict access to web scrapers or bots.

def table_scraping(url):
    page = requests.get(url,headers = {"User-Agent":"Mozilla/5.0"})
    page.raise_for_status() #identifies if the request failed (e.g., 404)
    
    soup = BeautifulSoup(page.text, "html.parser")
    tables = soup.find_all("table") #grabs every <table> element on the page, which are typically used in datasets.
    if not tables:
        raise ValueError("No tables found.")
    
    data = []
    
    for table in tables:
        rows = table.find_all("tr") #<tr> = table row
        if not rows:
            continue
        
        #The first row will be treated as a header row
        
        headers = [
            cell.get_text("", strip=True) #pulls only the text content of each cell in the header row
            for cell in rows[0].find_all(["th","td"])] #<th> = table header, <td> = table data cell
        
        table_data = []
        
        for row in rows[1:]:
            cells = row.find_all(["td","th"])
            values = [cell.get_text("", strip = True)
                    for cell in cells]
            
            #only keeping rows with as many cells as there are headers,
            #to avoid misaligned columns from deformed table rows.
            
            if len(values) == len(headers):
                table_data.append(values)
        
        if headers:
            table_df = pd.DataFrame(table_data, columns = headers)
            
            #This will drop any column in the dataframe that contains only empty strings
            #df.loc is used to select rows and columns based on labels or boolean conditions.
            
            table_df = table_df.loc[:, (table_df != "").any()]
            data.append(table_df)
    return data

def clean_dataframe(df):
    
    #Attempts to convert text-based numeric columns, into actual numbers to be used/processed.
    
    df = df.copy()
    for col in df.columns:
        sample = df[col].astype(str).str.strip()
        
        #Convert shorthand suffixes into scientific notation,
        #so pd.to_numeric can parse them
        
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