import streamlit as st
import pandas as pd

st.set_page_config(page_title="Excel-like Spreadsheet App")
st.title("Excel-like Spreadsheet App")
st.write("Enter or paste data in the cells below. Add or delete rows dynamically.")

# Initialize session state to keep dataframe
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame({"Column 1": [""], "Column 2": [""]})

# Display dataframe editor
edited_df = st.experimental_data_editor(st.session_state.df, num_rows="dynamic")

# Update session state
st.session_state.df = edited_df

st.write("### Current Data")
st.dataframe(st.session_state.df)

# Download button
csv = st.session_state.df.to_csv(index=False)
st.download_button(label="Download CSV", data=csv, file_name="spreadsheet_data.csv", mime="text/csv")
