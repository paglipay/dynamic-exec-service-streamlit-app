import streamlit as st

st.set_page_config(page_title="IT Support Request Form")
st.title("IT Support Request Form")
st.write("Please fill out the form below to submit an IT support request.")

with st.form(key="it_support_form"):
    name = st.text_input("Name", placeholder="Enter your full name", max_chars=100, help="This field is required.")
    department = st.text_input("Department", placeholder="Enter your department or team", help="Optional field.")
    contact_info = st.text_input("Contact Information", placeholder="Email or phone number", help="This field is required.")
    issue_description = st.text_area("Issue Description", placeholder="Describe the issue you're facing", help="This field is required.")
    priority = st.selectbox("Priority Level", ["Low", "Medium", "High", "Urgent"], help="Select the priority of your request")
    submitted = st.form_submit_button("Submit Request")

    # Check required fields
    if submitted:
        if not name or not contact_info or not issue_description:
            st.error("Please fill in all required fields (Name, Contact Information, Issue Description).")
        else:
            st.success(f"Thank you {name}, your support request has been submitted.")
            st.json({"Name": name, "Department": department, "Contact": contact_info, "Issue Description": issue_description, "Priority": priority})
