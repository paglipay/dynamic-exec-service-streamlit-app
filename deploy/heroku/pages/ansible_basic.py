import streamlit as st
from _auth_guard import require_authentication

st.set_page_config(page_title="Ansible Demo")
require_authentication("Ansible Demo")
st.title("Ansible Basic Configuration Demo")

device_type = st.selectbox("Select Device Type", ["Cisco Router", "Cisco Switch", "Linux Server", "Windows Server"])

st.write("### Configuration Template")

if device_type == "Cisco Router":
    config = st.text_area("Enter Cisco Router Configuration", "interface GigabitEthernet0/1\n ip address 10.0.0.1 255.255.255.0\n no shutdown")
elif device_type == "Cisco Switch":
    config = st.text_area("Enter Cisco Switch Configuration", "vlan 10\n name Users\ninterface FastEthernet0/1\n switchport mode access")
elif device_type == "Linux Server":
    config = st.text_area("Enter Linux Server Configuration", "---\n- hosts: all\n  become: yes\n  tasks:\n    - name: Update and upgrade apt packages\n      apt:\n        update_cache: yes\n        upgrade: dist")
elif device_type == "Windows Server":
    config = st.text_area("Enter Windows Server Configuration", "---\n- hosts: all\n  tasks:\n    - name: Install IIS\n      win_feature:\n        name: Web-Server\n        state: present")

if st.button("Show Configuration"):
    st.subheader("Configuration to be applied")
    st.code(config, language='yaml')
