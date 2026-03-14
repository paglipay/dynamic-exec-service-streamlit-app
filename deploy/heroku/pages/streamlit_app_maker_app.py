import streamlit as st
from streamlit_elements import elements, mui

st.set_page_config(page_title="Streamlit App Maker")
st.title("Streamlit App Maker")
st.write("Create a form by selecting elements and placing them on the canvas.")

if "elements" not in st.session_state:
    st.session_state.elements = []

st.subheader("Elements")
controls = st.columns(4)

with controls[0]:
    if st.button("Add Text Input", use_container_width=True):
        st.session_state.elements.append(
            {"type": "text_input", "label": f"Text Input {len(st.session_state.elements) + 1}"}
        )

with controls[1]:
    if st.button("Add Number Input", use_container_width=True):
        st.session_state.elements.append(
            {"type": "number_input", "label": f"Number Input {len(st.session_state.elements) + 1}"}
        )

with controls[2]:
    if st.button("Add Select Box", use_container_width=True):
        st.session_state.elements.append(
            {
                "type": "select_box",
                "label": f"Select Box {len(st.session_state.elements) + 1}",
                "options": ["Option 1", "Option 2", "Option 3"],
            }
        )

with controls[3]:
    if st.button("Clear Canvas", use_container_width=True):
        st.session_state.elements = []

st.subheader("Form Preview")

if not st.session_state.elements:
    st.info("Add an element to preview the generated form.")
else:
    with elements("form_maker_preview"):
        with mui.Paper(elevation=1, sx={"padding": 3, "borderRadius": 2}):
            with mui.Stack(spacing=2):
                for elem in st.session_state.elements:
                    if elem["type"] == "text_input":
                        mui.TextField(label=elem["label"], fullWidth=True, disabled=True)
                    elif elem["type"] == "number_input":
                        mui.TextField(label=elem["label"], type="number", fullWidth=True, disabled=True)
                    elif elem["type"] == "select_box":
                        with mui.TextField(
                            label=elem["label"],
                            value=elem["options"][0],
                            select=True,
                            fullWidth=True,
                            disabled=True,
                        ):
                            for option in elem["options"]:
                                mui.MenuItem(option, value=option)

if st.button("Publish Form"):
    st.success("Form published! You can implement publishing logic here.")
