import streamlit as st
import os
import importlib.util
import sys
from pathlib import Path

st.set_page_config(page_title="Streamlit Multi-App Launcher")

PAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pages")
assistant_module_path = os.path.join(PAGE_DIR, "_ai_assistant_panel.py")
assistant_spec = importlib.util.spec_from_file_location(
    "assistant_panel", assistant_module_path
)
assistant_mod = importlib.util.module_from_spec(assistant_spec)
assistant_spec.loader.exec_module(assistant_mod)
render_ai_assistant_panel = assistant_mod.render_ai_assistant_panel

render_ai_assistant_panel("Multi-App Launcher")

st.title("Streamlit Multi-App Launcher")
st.write("Select and run Streamlit apps from the pages/ directory below.")

# Get list of Python files in pages folder
app_files = [
    f
    for f in os.listdir(PAGE_DIR)
    if f.endswith('.py') and not Path(f).name.startswith("_")
]
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
