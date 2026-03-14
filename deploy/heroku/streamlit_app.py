import streamlit as st
import requests
import json

st.set_page_config(page_title="JSON Payload Submitter")
st.title("JSON Payload Submitter Form")
st.write("Use this form to submit a JSON payload to a specified URL.")

with st.form(key="json_submit_form"):
    url = st.text_input("URL to POST JSON payload to")
    json_text = st.text_area("JSON Payload")
    submit_button = st.form_submit_button("Submit")

if submit_button:
    try:
        data = json.loads(json_text)
        response = requests.post(url, json=data)
        st.success(f"Request successful with status code: {response.status_code}")
        st.json(response.json())
    except Exception as e:
        st.error(f"Error submitting request: {e}")
