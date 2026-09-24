import streamlit as st
import requests
from _auth_guard import require_authentication

st.set_page_config(page_title="API Explorer")
require_authentication("API Explorer")
st.title("API Explorer - Test and interact with APIs")

url = st.text_input("API URL", "https://jsonplaceholder.typicode.com/posts")
method = st.selectbox("HTTP Method", ["GET", "POST", "PUT", "DELETE"])

request_body = None
headers = {}

if method in ["POST", "PUT"]:
    request_body = st.text_area("Request Body (JSON)")
else:
    request_body = None

if st.button("Send Request"):
    try:
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            response = requests.post(url, data=request_body, headers=headers)
        elif method == "PUT":
            response = requests.put(url, data=request_body, headers=headers)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers)
        else:
            st.error("Unsupported HTTP method")
            response = None

        if response:
            st.write(f"Status code: {response.status_code}")
            try:
                st.json(response.json())
            except Exception:
                st.text(response.text)
    except Exception as e:
        st.error(f"Request failed: {e}")
