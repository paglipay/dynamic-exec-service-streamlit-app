import streamlit as st
import serial
import serial.tools.list_ports
import time
from _ai_assistant_panel import render_ai_assistant_panel
from _theme import apply_page_theme

apply_page_theme("USB Serial Console", "Connect, monitor, and send data over USB serial ports.")
render_ai_assistant_panel("USB Serial Console")

if "serial_conn" not in st.session_state:
    st.session_state.serial_conn = None
if "rx_log" not in st.session_state:
    st.session_state.rx_log = []
if "connected" not in st.session_state:
    st.session_state.connected = False

ports = [p.device for p in serial.tools.list_ports.comports()]

with st.sidebar:
    st.header("Connection Settings")
    port = st.selectbox("Serial Port", options=ports if ports else ["No ports detected"])
    baud_rate = st.selectbox("Baud Rate", [300, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200], index=8)
    data_bits = st.selectbox("Data Bits", [7, 8], index=1)
    parity = st.selectbox("Parity", ["N", "E", "O"], index=0)
    stop_bits = st.selectbox("Stop Bits", [1, 2], index=0)
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        connect_btn = st.button("Connect", disabled=st.session_state.connected, use_container_width=True)
    with col2:
        disconnect_btn = st.button("Disconnect", disabled=not st.session_state.connected, use_container_width=True)

    if connect_btn and ports:
        try:
            conn = serial.Serial(
                port=port,
                baudrate=baud_rate,
                bytesize=data_bits,
                parity=parity,
                stopbits=stop_bits,
                timeout=0.1,
            )
            st.session_state.serial_conn = conn
            st.session_state.connected = True
            st.success(f"Connected to {port} @ {baud_rate} baud")
        except serial.SerialException as exc:
            st.error(f"Failed to open {port}: {exc}")

    if disconnect_btn and st.session_state.serial_conn:
        st.session_state.serial_conn.close()
        st.session_state.serial_conn = None
        st.session_state.connected = False
        st.info("Disconnected")

st.subheader("Receive Buffer")
if st.button("Clear Log"):
    st.session_state.rx_log = []

if st.session_state.connected and st.session_state.serial_conn:
    try:
        waiting = st.session_state.serial_conn.in_waiting
        if waiting > 0:
            raw = st.session_state.serial_conn.read(waiting)
            text = raw.decode("utf-8", errors="replace")
            st.session_state.rx_log.append(text)
    except serial.SerialException as exc:
        st.error(f"Read error: {exc}")
        st.session_state.connected = False
        st.session_state.serial_conn = None

rx_display = "".join(st.session_state.rx_log[-500:])
st.text_area("RX", value=rx_display, height=300, disabled=True, key="rx_area")

st.divider()
st.subheader("Send Data")
with st.form("tx_form", clear_on_submit=True):
    tx_input = st.text_input("Data to send")
    add_newline = st.checkbox("Append CR+LF", value=True)
    send_btn = st.form_submit_button("Send", disabled=not st.session_state.connected)

if send_btn:
    if not st.session_state.connected or not st.session_state.serial_conn:
        st.warning("Not connected.")
    elif tx_input.strip():
        try:
            payload = (tx_input + "\r\n") if add_newline else tx_input
            st.session_state.serial_conn.write(payload.encode("utf-8"))
            st.session_state.rx_log.append(f"[TX] {tx_input}\n")
            st.success(f"Sent {len(payload)} bytes")
        except serial.SerialException as exc:
            st.error(f"Send error: {exc}")

if st.session_state.connected:
    time.sleep(0.3)
    st.rerun()
