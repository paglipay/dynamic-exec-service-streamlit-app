import streamlit as st
import os
import subprocess

st.set_page_config(page_title="Streamlit App Runner")
st.title("Streamlit App Runner")
st.write("Browse, view, and run other Streamlit .py apps in this folder.")

# List all .py files in current directory
app_folder = os.path.dirname(os.path.abspath(__file__))
py_files = [f for f in os.listdir(app_folder) if f.endswith('.py') and f != os.path.basename(__file__)]

selected_app = st.selectbox("Select a Streamlit app to view and run", py_files)

if selected_app:
    app_path = os.path.join(app_folder, selected_app)
    st.write(f"## {selected_app} contents")
    with open(app_path, 'r', encoding='utf-8') as f:
        code = f.read()
    st.code(code, language='python')

    if st.button(f"Run {selected_app}"):
        st.write(f"Running {selected_app}...")
        # To run the app, launch a subprocess (non-blocking)
        proc = subprocess.Popen(['streamlit', 'run', app_path])
        st.write(f"App {selected_app} started with PID {proc.pid}")
        st.info("Note: Running subprocess will not show output here.")

st.write("Note: Only one app can be run at a time. You must stop it manually.")
