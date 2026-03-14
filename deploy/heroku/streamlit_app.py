import streamlit as st
import serial
import threading
import time

st.set_page_config(page_title="USB Serial Console")
st.title("USB Serial Console")
st.write("Connect your USB Serial Console Cable and send/receive data.")

# Session state for serial port and data
if "serial_port" not in st.session_state:
    st.session_state.serial_port = None
if "received_data" not in st.session_state:
    st.session_state.received_data = ""
if "stop_thread" not in st.session_state:
    st.session_state.stop_thread = False

# Function to read from serial port

def read_from_port(ser):
    while not st.session_state.stop_thread:
        if ser.in_waiting > 0:
            data = ser.read(ser.in_waiting).decode(errors='ignore')
            st.session_state.received_data += data
            time.sleep(0.1)


ports_list = st.text_input("Enter Serial Port (e.g. COM3 or /dev/ttyUSB0):")

baud_rate = st.selectbox("Baud Rate", [9600, 19200, 38400, 57600, 115200], index=0)

if st.button("Connect"):
    try:
        if st.session_state.serial_port is not None:
            st.session_state.serial_port.close()

        ser = serial.Serial(port=ports_list, baudrate=baud_rate, timeout=0.1)
        st.session_state.serial_port = ser
        st.session_state.received_data = ""
        st.session_state.stop_thread = False

        # Start thread to read data
        thread = threading.Thread(target=read_from_port, args=(ser,), daemon=True)
        thread.start()
        st.success(f"Connected to {ports_list} at {baud_rate} baud.")
    except Exception as e:
        st.error(f"Failed to connect: {e}")

if st.session_state.serial_port and st.session_state.serial_port.is_open:
    send_data = st.text_input("Send Data:")
    if st.button("Send"):
        try:
            st.session_state.serial_port.write(send_data.encode())
            st.success("Data sent.")
        except Exception as e:
            st.error(f"Failed to send data: {e}")

    st.text_area("Received Data:", value=st.session_state.received_data, height=300)

if st.button("Disconnect") and st.session_state.serial_port:
    st.session_state.stop_thread = True
    st.session_state.serial_port.close()
    st.session_state.serial_port = None
    st.success("Disconnected.")
