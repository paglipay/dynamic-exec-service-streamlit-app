import streamlit as st
import requests
import json
from _ai_assistant_panel import render_ai_assistant_panel
from _theme import apply_page_theme

apply_page_theme("JSON Submitter", "Submit JSON payloads to external HTTP endpoints.")
render_ai_assistant_panel("JSON Submitter")
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
