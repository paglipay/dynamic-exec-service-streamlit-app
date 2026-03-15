import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

st.set_page_config(page_title="Data Dashboard")
st.title("Data Dashboard - Visualize and Analyze Data")

uploaded_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx"])

if uploaded_file is not None:
    file_type = uploaded_file.name.split('.')[-1]
    if file_type == "csv":
        df = pd.read_csv(uploaded_file)
    elif file_type == "xlsx":
        df = pd.read_excel(uploaded_file)
    else:
        st.error("Unsupported file type")
        df = None

    if df is not None:
        st.write("### Data Preview")
        st.dataframe(df.head())

        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        if numeric_cols:
            st.write("### Numeric Columns Analysis")
            selected_cols = st.multiselect("Select columns to analyze", numeric_cols, default=numeric_cols)

            if selected_cols:
                st.write("#### Correlation Matrix")
                corr = df[selected_cols].corr()
                st.write(corr)

                st.write("#### Pairplot")
                fig = sns.pairplot(df[selected_cols])
                st.pyplot(fig)

        st.write("### Summary Statistics")
        st.write(df.describe())
else:
    st.info("Please upload a CSV or Excel file to start.")
