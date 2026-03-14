import streamlit as st
from streamlit_elements import Elements, mui, event

st.set_page_config(page_title="Streamlit App Maker")
st.title("Streamlit App Maker")
st.write("Create a form by selecting elements and placing them on the canvas.")

if "elements" not in st.session_state:
    st.session_state.elements = []

with Elements(key="form_maker") as e:
    with mui.Grid(container=True, spacing=2):
        with mui.Grid(item=True, xs=3):
            st.write("# Elements")
            if mui.Button("Add Text Input").clicked():
                st.session_state.elements.append({"type": "text_input", "label": f"Text Input {len(st.session_state.elements)+1}"})
            if mui.Button("Add Number Input").clicked():
                st.session_state.elements.append({"type": "number_input", "label": f"Number Input {len(st.session_state.elements)+1}"})
            if mui.Button("Add Select Box").clicked():
                st.session_state.elements.append({"type": "select_box", "label": f"Select Box {len(st.session_state.elements)+1}", "options": ["Option 1", "Option 2", "Option 3"]})

        with mui.Grid(item=True, xs=9):
            st.write("# Form Preview")
            for i, elem in enumerate(st.session_state.elements):
                if elem["type"] == "text_input":
                    e.text_field(label=elem["label"], key=f"text_input_{i}")
                elif elem["type"] == "number_input":
                    e.number_field(label=elem["label"], key=f"number_input_{i}")
                elif elem["type"] == "select_box":
                    e.select(label=elem["label"], options=elem["options"], key=f"select_box_{i}")

if st.button("Publish Form"):
    st.success("Form published! You can implement publishing logic here.")
