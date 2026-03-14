import streamlit as st

st.set_page_config(page_title="IT Support Request Form")
st.title("IT Support Request Form")
st.write("Please fill out the form below to submit an IT support request.")

with st.form(key="it_support_form"):
    name = st.text_input("Name", help="Enter your full name")
    department = st.text_input("Department", help="Your department or team")
    contact_info = st.text_input("Contact Information", help="Email or phone number")
    issue_description = st.text_area("Issue Description", help="Briefly describe your issue")
    priority = st.selectbox("Priority Level", ["Low", "Medium", "High", "Urgent"], help="Select the priority of your request")
    submit_button = st.form_submit_button("Submit Request")

if submit_button:
    st.success(f"Thank you {name}, your support request has been submitted.")
    st.json({"Name": name, "Department": department, "Contact": contact_info, "Issue Description": issue_description, "Priority": priority})
