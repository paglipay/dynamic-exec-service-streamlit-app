import streamlit as st

st.set_page_config(page_title='Dynamic Streamlit UI')
st.title('Dynamic Streamlit UI')
st.write('Updated from Flask via GitHub API commit.')

with st.form(key='dynamic_form'):
    name = st.text_input('Name')
    email = st.text_input('Email')
    submitted = st.form_submit_button('Submit')

if submitted:
    st.success('Submitted')
    st.json({'name': name, 'email': email})
