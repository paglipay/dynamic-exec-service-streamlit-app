import streamlit as st
import os
from _ai_assistant_panel import render_ai_assistant_panel
from _theme import apply_page_theme

apply_page_theme("README Viewer", "Read local project documentation directly in-app.")
render_ai_assistant_panel("README Viewer")
st.write("Displays the contents of the README.md file in this folder as markdown.")

readme_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md")

if os.path.exists(readme_path):
    with open(readme_path, "r", encoding="utf-8") as file:
        content = file.read()
    st.markdown(content)
else:
    st.warning("README.md file not found in this directory.")
