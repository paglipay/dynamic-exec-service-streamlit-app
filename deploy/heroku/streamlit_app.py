import streamlit as st
import pandas as pd
from io import StringIO

st.set_page_config(page_title="Simple Spreadsheet App")
st.title("Simple Spreadsheet App with Editable HTML Table")
st.write("Edit the table cells and then submit to update the data.")

# Initial dataframe
if 'df' not in st.session_state:
    st.session_state.df = pd.DataFrame({"Column 1": ["", ""], "Column 2": ["", ""]})

# Render editable HTML table
html_table = st.session_state.df.to_html(index=False, escape=False, table_id="editable_table")

def generate_html_table(df):
    table_html = '<table id="editable_table" contenteditable="true" border="1" style="border-collapse: collapse; width: 100%;">'
    table_html += "<thead><tr>"
    for col in df.columns:
        table_html += f"<th>{col}</th>"
    table_html += "</tr></thead><tbody>"
    for i, row in df.iterrows():
        table_html += "<tr>"
        for cell in row:
            table_html += f"<td contenteditable=\"true\">{cell}</td>"
        table_html += "</tr>"
    table_html += "</tbody></table>"
    return table_html

editable_table_html = generate_html_table(st.session_state.df)

st.markdown(editable_table_html, unsafe_allow_html=True)

st.write("")

# Hidden text area to capture edited table as CSV
edited_csv = st.text_area("Edited CSV", height=200, help="Paste CSV exported from the table here to update.")

if st.button("Update Data from CSV"):
    try:
        df_new = pd.read_csv(StringIO(edited_csv))
        st.session_state.df = df_new
        st.success("Data updated successfully.")
    except Exception as e:
        st.error(f"Failed to update data: {e}")

st.write("### Current Data")
st.dataframe(st.session_state.df)

csv = st.session_state.df.to_csv(index=False)
st.download_button(label="Download CSV", data=csv, file_name="spreadsheet_data.csv", mime="text/csv")
