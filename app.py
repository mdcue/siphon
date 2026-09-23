import streamlit as st
import io
from webScrapper import table_scraping, clean_dataframe

st.title("*<siphon>*")
st.header("A python based web scraper.")

url = st.text_input("Enter the URL of the website to scrape: ")
file_format = st.selectbox("Output format: ", [".csv(Comma-Separated Values)", ".xlsx(Excel Sheet)"])
clean = st.checkbox("Further cleaning for numeric data (i.e. currency, percentages. etc...)")

if st.button("Scrape"):
    if not url:
        st.error("Please enter a valid URL.")
    else:
        try:
            tables = table_scraping(url)
        except ValueError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Failed to fetch page: {e}")
        else:
            st.success(f"Found {len(tables)} table(s).")
            
            if clean:
                tables = [clean_dataframe(df) for df in tables]
            
            for i, df in enumerate(tables, start = 1):
                st.subheader(f"Table {i}")
                st.dataframe(df)
                
                if file_format == "csv":
                    st.download_button(
                        label = f"Download Table {i} as CSV",
                        data = df.to_csv(index = False),
                        file_name = f"table_{i}.csv",
                        mime = "text/csv"
                    )
                else:
                    buffer = io.BytesIO()
                    df.to_excel(buffer, index = False, engine = "openpyxl")
                    st.download_button(
                        label = f"Download Table {i} as Excel",
                        data = buffer.getvalue(),
                        file_name = f"table_{i}.xlsx",
                        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
