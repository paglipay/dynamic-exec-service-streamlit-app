import streamlit as st

st.set_page_config(page_title='Dynamic Streamlit UI')
st.title('Dynamic Streamlit UI')
st.write('Execute test commit from dynamic-exec-service.')
st.caption('If you see this caption in production, /execute commit flow worked.')

with st.form(key='dynamic_form'):
    name = st.text_input('Name')
    email = st.text_input('Email')
    submitted = st.form_submit_button('Submit')

if submitted:
    st.success('Submitted')
    st.json({'name': name, 'email': email})
