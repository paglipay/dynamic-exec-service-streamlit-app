import streamlit as st
import os
import importlib.util
import sys

st.set_page_config(page_title="Streamlit Multi-App Launcher")
st.title("Streamlit Multi-App Launcher")
st.write("Select and run Streamlit apps from the pages/ directory below.")

PAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pages")

# Get list of Python files in pages folder
app_files = [f for f in os.listdir(PAGE_DIR) if f.endswith('.py')]
selected_app = st.selectbox("Select app", app_files)

if selected_app:
    app_path = os.path.join(PAGE_DIR, selected_app)

    st.write(f"## Showing {selected_app}")

    # Read and display source code
    with open(app_path, 'r', encoding='utf-8') as f:
        code = f.read()
    st.code(code, language='python')

    # Import and run app
    try:
        spec = importlib.util.spec_from_file_location("mod", app_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["mod"] = mod
        spec.loader.exec_module(mod)

        if hasattr(mod, "app"):
            mod.app()
        else:
            st.warning("Selected app does not have an 'app' function to run.")

    except Exception as e:
        st.error(f"Failed to run app: {e}")
