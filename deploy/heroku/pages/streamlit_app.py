import streamlit as st
import os
from _ai_assistant_panel import render_ai_assistant_panel

st.set_page_config(page_title="Display README.md")
render_ai_assistant_panel("README Viewer")
st.title("README.md Viewer")
st.write("Displays the contents of the README.md file in this folder as markdown.")

readme_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md")

if os.path.exists(readme_path):
    with open(readme_path, "r", encoding="utf-8") as file:
        content = file.read()
    st.markdown(content)
else:
    st.warning("README.md file not found in this directory.")
