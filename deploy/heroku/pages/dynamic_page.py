import json
import queue
import threading
import time
from copy import deepcopy
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, parse, request

import streamlit as st


HTTP_MESSAGE_QUEUE: queue.Queue[dict] = queue.Queue()
HTTP_SERVER_THREAD: threading.Thread | None = None
HTTP_SERVER_INSTANCE: ThreadingHTTPServer | None = None
HTTP_LOCK = threading.Lock()


DEFAULT_SAMPLES = [
	{
		"name": "Contact Form",
		"schema": {
			"title": "Contact Form",
			"description": "Share your contact details.",
			"elements": [
				{"type": "text_input", "label": "Full Name", "key": "full_name", "placeholder": "Jane Doe"},
				{"type": "text_input", "label": "Email", "key": "email", "placeholder": "jane@example.com"},
				{"type": "selectbox", "label": "Topic", "key": "topic", "options": ["Sales", "Support", "Partnership"]},
				{"type": "text_area", "label": "Message", "key": "message", "placeholder": "Tell us how we can help"},
				{"type": "button", "label": "Send", "method": "POST", "url": ""}
			]
		},
	},
	{
		"name": "Bug Report",
		"schema": {
			"title": "Bug Report",
			"description": "Capture issue details quickly.",
			"elements": [
				{"type": "text_input", "label": "Issue Title", "key": "issue_title"},
				{"type": "selectbox", "label": "Severity", "key": "severity", "options": ["Low", "Medium", "High", "Critical"]},
				{"type": "text_area", "label": "Steps to Reproduce", "key": "steps"},
				{"type": "checkbox", "label": "Blocks release", "key": "blocks_release", "value": False},
				{"type": "button", "label": "Submit Bug", "method": "POST", "url": ""}
			]
		},
	},
	{
		"name": "Event RSVP",
		"schema": {
			"title": "Event RSVP",
			"elements": [
				{"type": "text_input", "label": "Attendee Name", "key": "attendee_name"},
				{"type": "selectbox", "label": "Will Attend", "key": "attendance", "options": ["Yes", "No", "Maybe"]},
				{"type": "number_input", "label": "Guests", "key": "guests", "min_value": 0, "max_value": 5, "value": 1, "step": 1},
				{"type": "date_input", "label": "Arrival Date", "key": "arrival_date"},
				{"type": "button", "label": "Submit RSVP", "method": "POST", "url": ""}
			]
		},
	},
	{
		"name": "Hiring Intake",
		"schema": {
			"title": "Hiring Intake",
			"elements": [
				{"type": "text_input", "label": "Role Name", "key": "role_name"},
				{"type": "selectbox", "label": "Department", "key": "department", "options": ["Engineering", "Operations", "Finance", "People"]},
				{"type": "slider", "label": "Seniority", "key": "seniority", "min_value": 1, "max_value": 10, "value": 5},
				{"type": "checkbox", "label": "Urgent", "key": "urgent", "value": True},
				{"type": "button", "label": "Submit Intake", "method": "POST", "url": ""}
			]
		},
	},
	{
		"name": "Trip Planner",
		"schema": {
			"title": "Trip Planner",
			"description": "Plan your next trip.",
			"elements": [
				{"type": "text_input", "label": "Destination", "key": "destination"},
				{"type": "date_input", "label": "Departure Date", "key": "departure_date"},
				{"type": "number_input", "label": "Travelers", "key": "travelers", "min_value": 1, "max_value": 12, "value": 2, "step": 1},
				{"type": "text_area", "label": "Preferences", "key": "preferences"},
				{"type": "button", "label": "Submit Trip", "method": "POST", "url": ""}
			]
		},
	},
	{
		"name": "Feature Request",
		"schema": {
			"title": "Feature Request",
			"elements": [
				{"type": "text_input", "label": "Feature Name", "key": "feature_name"},
				{"type": "text_area", "label": "Problem Statement", "key": "problem_statement"},
				{"type": "text_area", "label": "Proposed Solution", "key": "proposed_solution"},
				{"type": "selectbox", "label": "Impact", "key": "impact", "options": ["Small", "Medium", "Large"]},
				{"type": "button", "label": "Submit Request", "method": "POST", "url": ""}
			]
		},
	},
	{
		"name": "Customer Survey",
		"schema": {
			"title": "Customer Survey",
			"elements": [
				{"type": "slider", "label": "Overall Satisfaction", "key": "satisfaction", "min_value": 1, "max_value": 10, "value": 8},
				{"type": "selectbox", "label": "How likely to recommend?", "key": "recommend", "options": ["Not likely", "Maybe", "Likely"]},
				{"type": "text_area", "label": "Feedback", "key": "feedback"},
				{"type": "button", "label": "Submit Survey", "method": "POST", "url": ""}
			]
		},
	},
	{
		"name": "Daily Standup",
		"schema": {
			"title": "Daily Standup",
			"elements": [
				{"type": "text_area", "label": "Yesterday", "key": "yesterday"},
				{"type": "text_area", "label": "Today", "key": "today"},
				{"type": "text_area", "label": "Blockers", "key": "blockers"},
				{"type": "checkbox", "label": "Need Help", "key": "need_help", "value": False},
				{"type": "button", "label": "Submit Standup", "method": "POST", "url": ""}
			]
		},
	},
	{
		"name": "Inventory Update",
		"schema": {
			"title": "Inventory Update",
			"elements": [
				{"type": "text_input", "label": "SKU", "key": "sku"},
				{"type": "number_input", "label": "Quantity", "key": "quantity", "min_value": 0, "max_value": 10000, "value": 0, "step": 1},
				{"type": "selectbox", "label": "Warehouse", "key": "warehouse", "options": ["A", "B", "C"]},
				{"type": "checkbox", "label": "Backordered", "key": "backordered", "value": False},
				{"type": "button", "label": "Submit Update", "method": "POST", "url": ""}
			]
		},
	},
	{
		"name": "Simple Registration",
		"schema": {
			"title": "Simple Registration",
			"elements": [
				{"type": "text_input", "label": "First Name", "key": "first_name"},
				{"type": "text_input", "label": "Last Name", "key": "last_name"},
				{"type": "text_input", "label": "Phone", "key": "phone"},
				{"type": "checkbox", "label": "Agree to Terms", "key": "agree_terms", "value": False},
				{"type": "button", "label": "Register", "method": "POST", "url": ""}
			]
		},
	},
]


def to_json_text(schema: dict) -> str:
	return json.dumps(schema, indent=2)


def normalize_key(raw_key: str, fallback: str) -> str:
	key = (raw_key or "").strip().lower().replace(" ", "_")
	return key or fallback


def init_state() -> None:
	if "samples" not in st.session_state:
		st.session_state.samples = deepcopy(DEFAULT_SAMPLES)

	if "selected_sample_name" not in st.session_state:
		st.session_state.selected_sample_name = st.session_state.samples[0]["name"]

	if "json_text" not in st.session_state:
		st.session_state.json_text = to_json_text(st.session_state.samples[0]["schema"])

	if "rendered_schema" not in st.session_state:
		st.session_state.rendered_schema = st.session_state.samples[0]["schema"]

	if "render_error" not in st.session_state:
		st.session_state.render_error = ""

	if "http_listener_host" not in st.session_state:
		st.session_state.http_listener_host = "0.0.0.0"

	if "http_listener_port" not in st.session_state:
		st.session_state.http_listener_port = 8765

	if "http_listener_path" not in st.session_state:
		st.session_state.http_listener_path = "/json-update"

	if "http_listener_status" not in st.session_state:
		st.session_state.http_listener_status = "Stopped"

	if "http_listener_running" not in st.session_state:
		st.session_state.http_listener_running = False

	if "http_last_payload" not in st.session_state:
		st.session_state.http_last_payload = ""

	if "http_auto_poll" not in st.session_state:
		st.session_state.http_auto_poll = True

	if "http_poll_interval" not in st.session_state:
		st.session_state.http_poll_interval = 1


def sample_names() -> list[str]:
	return [sample["name"] for sample in st.session_state.samples]


def get_selected_sample() -> dict:
	selected_name = st.session_state.selected_sample_name
	for sample in st.session_state.samples:
		if sample["name"] == selected_name:
			return sample
	return st.session_state.samples[0]


def load_selected_sample_into_textarea() -> None:
	selected = get_selected_sample()
	st.session_state.json_text = to_json_text(selected["schema"])


def validate_schema(schema: dict) -> tuple[bool, str]:
	if not isinstance(schema, dict):
		return False, "Schema must be a JSON object."

	elements = schema.get("elements")
	if not isinstance(elements, list):
		return False, "Schema must include an 'elements' list."

	for idx, element in enumerate(elements):
		if not isinstance(element, dict):
			return False, f"Element #{idx + 1} must be an object."
		if "type" not in element:
			return False, f"Element #{idx + 1} is missing 'type'."
		if element.get("type") != "button" and "key" not in element:
			return False, f"Element #{idx + 1} is missing 'key'."
		if element.get("type") == "button":
			method = str(element.get("method", "POST")).upper()
			if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
				return False, f"Element #{idx + 1} has invalid button method '{method}'."

	return True, ""


def parse_and_store_render_schema() -> None:
	try:
		parsed = json.loads(st.session_state.json_text)
	except json.JSONDecodeError as exc:
		st.session_state.render_error = f"Invalid JSON: {exc}"
		return

	valid, message = validate_schema(parsed)
	if not valid:
		st.session_state.render_error = message
		return

	st.session_state.rendered_schema = parsed
	st.session_state.render_error = ""


def _build_json_text_from_body(raw_body: str) -> str:
	raw_body = raw_body.strip()
	if not raw_body:
		raise ValueError("POST body is empty")

	parsed_body = json.loads(raw_body)
	if isinstance(parsed_body, dict):
		if "json_text" in parsed_body and isinstance(parsed_body["json_text"], str):
			return parsed_body["json_text"]
		if "schema" in parsed_body:
			return json.dumps(parsed_body["schema"], indent=2)
	return json.dumps(parsed_body, indent=2)


def _enqueue_http_status(message: str) -> None:
	HTTP_MESSAGE_QUEUE.put({"type": "status", "message": message})


def _make_listener_handler(expected_path: str):
	class ListenerHandler(BaseHTTPRequestHandler):
		def _send_json(self, status_code: int, payload: dict) -> None:
			body = json.dumps(payload).encode("utf-8")
			self.send_response(status_code)
			self.send_header("Content-Type", "application/json")
			self.send_header("Content-Length", str(len(body)))
			self.end_headers()
			self.wfile.write(body)

		def do_GET(self) -> None:  # noqa: N802
			if self.path == "/health":
				self._send_json(200, {"status": "ok"})
				return
			self._send_json(404, {"error": "Not found"})

		def do_POST(self) -> None:  # noqa: N802
			request_path = parse.urlparse(self.path).path
			if request_path != expected_path:
				self._send_json(404, {"error": f"Use POST {expected_path}"})
				return

			try:
				content_length = int(self.headers.get("Content-Length", "0"))
			except ValueError:
				content_length = 0

			raw = self.rfile.read(content_length).decode("utf-8", errors="replace")
			try:
				json_text = _build_json_text_from_body(raw)
			except Exception as exc:  # noqa: BLE001
				self._send_json(400, {"error": f"Invalid payload: {exc}"})
				return

			HTTP_MESSAGE_QUEUE.put({"type": "schema", "json_text": json_text})
			self._send_json(200, {"status": "accepted"})

		def log_message(self, format: str, *args):  # noqa: A003
			return

	return ListenerHandler


def _http_listener_worker(host: str, port: int, path: str) -> None:
	global HTTP_SERVER_INSTANCE
	try:
		handler = _make_listener_handler(path)
		httpd = ThreadingHTTPServer((host, port), handler)
		with HTTP_LOCK:
			HTTP_SERVER_INSTANCE = httpd
		_enqueue_http_status(f"Listening on http://{host}:{port}{path}")
		httpd.serve_forever(poll_interval=0.5)
	except Exception as exc:  # noqa: BLE001
		_enqueue_http_status(f"Listener error: {exc}")
	finally:
		with HTTP_LOCK:
			HTTP_SERVER_INSTANCE = None


def start_http_listener(host: str, port: int, path: str) -> tuple[bool, str]:
	global HTTP_SERVER_THREAD
	if not path.startswith("/"):
		return False, "Path must start with '/'."

	stop_http_listener()
	try:
		port = int(port)
	except Exception:  # noqa: BLE001
		return False, "Port must be a valid integer."

	with HTTP_LOCK:
		HTTP_SERVER_THREAD = threading.Thread(
			target=_http_listener_worker,
			args=(host.strip() or "0.0.0.0", port, path.strip() or "/json-update"),
			daemon=True,
		)
		HTTP_SERVER_THREAD.start()

	return True, "HTTP listener started."


def stop_http_listener() -> None:
	global HTTP_SERVER_THREAD
	with HTTP_LOCK:
		if HTTP_SERVER_INSTANCE is not None:
			try:
				HTTP_SERVER_INSTANCE.shutdown()
			except Exception:  # noqa: BLE001
				pass
		HTTP_SERVER_THREAD = None


def drain_http_messages() -> int:
	processed = 0
	while not HTTP_MESSAGE_QUEUE.empty():
		message = HTTP_MESSAGE_QUEUE.get_nowait()
		processed += 1
		if message.get("type") == "status":
			status_text = str(message.get("message", ""))
			st.session_state.http_listener_status = status_text
			st.session_state.http_listener_running = status_text.startswith("Listening")
		elif message.get("type") == "schema":
			json_text = str(message.get("json_text", ""))
			st.session_state.http_last_payload = json_text
			st.session_state.json_text = json_text
			parse_and_store_render_schema()

	return processed


def add_current_json_as_sample(name: str) -> tuple[bool, str]:
	cleaned_name = name.strip()
	if not cleaned_name:
		return False, "Provide a sample name."

	try:
		parsed = json.loads(st.session_state.json_text)
	except json.JSONDecodeError as exc:
		return False, f"Cannot add sample. JSON is invalid: {exc}"

	valid, message = validate_schema(parsed)
	if not valid:
		return False, f"Cannot add sample. {message}"

	existing_names = set(sample_names())
	unique_name = cleaned_name
	suffix = 2
	while unique_name in existing_names:
		unique_name = f"{cleaned_name} ({suffix})"
		suffix += 1

	st.session_state.samples.append({"name": unique_name, "schema": parsed})
	st.session_state.selected_sample_name = unique_name
	return True, f"Sample '{unique_name}' added."


def render_dynamic_element(element: dict, idx: int, used_keys: set[str]):
	elem_type = element.get("type", "")
	if elem_type == "button":
		return None, None

	key = normalize_key(element.get("key", ""), f"field_{idx + 1}")
	if key in used_keys:
		key = f"{key}_{idx + 1}"
	used_keys.add(key)

	label = element.get("label", key)
	help_text = element.get("help", None)

	if elem_type == "header":
		st.header(element.get("text", label))
		return None, None
	if elem_type == "subheader":
		st.subheader(element.get("text", label))
		return None, None
	if elem_type == "markdown":
		st.markdown(element.get("text", ""))
		return None, None
	if elem_type == "text_input":
		value = st.text_input(label, key=key, placeholder=element.get("placeholder", ""), help=help_text)
		return key, value
	if elem_type == "text_area":
		value = st.text_area(label, key=key, placeholder=element.get("placeholder", ""), help=help_text)
		return key, value
	if elem_type == "number_input":
		value = st.number_input(
			label,
			key=key,
			min_value=element.get("min_value", 0),
			max_value=element.get("max_value", 100),
			value=element.get("value", 0),
			step=element.get("step", 1),
			help=help_text,
		)
		return key, value
	if elem_type == "selectbox":
		value = st.selectbox(label, options=element.get("options", ["Option 1"]), key=key, help=help_text)
		return key, value
	if elem_type == "checkbox":
		value = st.checkbox(label, value=element.get("value", False), key=key, help=help_text)
		return key, value
	if elem_type == "slider":
		value = st.slider(
			label,
			min_value=element.get("min_value", 0),
			max_value=element.get("max_value", 100),
			value=element.get("value", 25),
			key=key,
			help=help_text,
		)
		return key, value
	if elem_type == "date_input":
		value = st.date_input(label, key=key, help=help_text)
		return key, value

	st.warning(f"Unsupported element type: {elem_type}")
	return None, None


def to_json_safe(value):
	if isinstance(value, (date, datetime)):
		return value.isoformat()
	return value


def send_http_request(method: str, url: str, payload: dict) -> tuple[bool, str, int | None]:
	clean_method = method.upper().strip()
	if clean_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
		return False, f"Unsupported HTTP method: {clean_method}", None

	if not url.strip():
		return False, "Submit URL is empty.", None

	try:
		if clean_method == "GET":
			query = parse.urlencode(payload, doseq=True)
			separator = "&" if "?" in url else "?"
			target_url = f"{url}{separator}{query}" if query else url
			req = request.Request(target_url, method=clean_method)
		else:
			data = json.dumps(payload).encode("utf-8")
			req = request.Request(
				url,
				data=data,
				method=clean_method,
				headers={"Content-Type": "application/json", "Accept": "application/json"},
			)

		with request.urlopen(req, timeout=15) as response:
			body = response.read().decode("utf-8", errors="replace")
			return True, body, response.getcode()
	except error.HTTPError as exc:
		body = exc.read().decode("utf-8", errors="replace")
		return False, body or str(exc), exc.code
	except Exception as exc:  # noqa: BLE001
		return False, str(exc), None


def render_canvas(schema: dict) -> None:
	st.markdown(f"### {schema.get('title', 'Dynamic Canvas')}")
	if schema.get("description"):
		st.caption(schema["description"])

	button_elements = [element for element in schema.get("elements", []) if element.get("type") == "button"]
	has_submit_button = len(button_elements) > 0
	used_keys: set[str] = set()
	submitted_data: dict[str, object] = {}
	clicked_button = None
	with st.form("dynamic_canvas_form"):
		for idx, element in enumerate(schema.get("elements", [])):
			result_key, result_value = render_dynamic_element(element, idx, used_keys)
			if result_key is not None:
				submitted_data[result_key] = to_json_safe(result_value)

		if has_submit_button:
			for button_idx, button_cfg in enumerate(button_elements):
				button_label = button_cfg.get("label", f"Submit {button_idx + 1}")
				if st.form_submit_button(button_label):
					clicked_button = button_cfg

	if not has_submit_button:
		st.info("Add an element with type 'button' to enable submission.")
		return

	if clicked_button:
		st.success("Form submitted.")
		st.json(submitted_data)

		submit_method = str(clicked_button.get("method", schema.get("submit_method", "POST"))).upper()
		submit_url = str(clicked_button.get("url", schema.get("submit_url", ""))).strip()
		if submit_url:
			st.caption(f"Submit target: {submit_method} {submit_url}")
		if submit_url:
			ok, response_body, status_code = send_http_request(submit_method, submit_url, submitted_data)
			if ok:
				st.success(f"Request sent successfully ({status_code}).")
				if response_body:
					st.code(response_body, language="json")
			else:
				if status_code is not None:
					st.error(f"Request failed with status {status_code}.")
				else:
					st.error("Request failed.")
				st.code(response_body)


def app() -> None:
	st.set_page_config(page_title="Dynamic JSON Canvas", layout="wide")
	init_state()
	processed_http_messages = drain_http_messages()

	st.title("Dynamic JSON Canvas Renderer")
	st.write("Pick a sample JSON, edit it, and press Render Canvas to quickly update the canvas.")

	left, right = st.columns([1, 1.4], gap="large")

	with left:
		st.subheader("JSON Editor")

		with st.expander("HTTP Update Listener", expanded=False):
			st.text_input("Bind Host", key="http_listener_host")
			st.number_input("Bind Port", min_value=1, max_value=65535, key="http_listener_port")
			st.text_input("POST Path", key="http_listener_path")

			listener_cols = st.columns(2)
			with listener_cols[0]:
				if st.button("Start Listener", use_container_width=True):
					ok, message = start_http_listener(
						st.session_state.http_listener_host,
						int(st.session_state.http_listener_port),
						st.session_state.http_listener_path,
					)
					if ok:
						st.success(message)
					else:
						st.error(message)
			with listener_cols[1]:
				if st.button("Stop Listener", use_container_width=True):
					stop_http_listener()
					st.session_state.http_listener_running = False
					st.session_state.http_listener_status = "Stopped"
					st.info("HTTP listener stopped.")

			st.checkbox("Auto Poll Listener", key="http_auto_poll")
			st.number_input("Poll Interval (seconds)", min_value=1, max_value=30, key="http_poll_interval")
			st.caption(f"Status: {st.session_state.http_listener_status}")
			if processed_http_messages > 0:
				st.caption(f"Processed {processed_http_messages} queued HTTP message(s) this run.")

			host = st.session_state.http_listener_host.strip() or "0.0.0.0"
			port = int(st.session_state.http_listener_port)
			path = st.session_state.http_listener_path.strip() or "/json-update"
			st.code(
				f"curl -X POST http://{host}:{port}{path} -H 'Content-Type: application/json' -d '{{\"schema\": {{\"title\": \"Live\", \"elements\": []}}}}'",
				language="bash",
			)

		st.selectbox(
			"Sample JSON",
			options=sample_names(),
			key="selected_sample_name",
			on_change=load_selected_sample_into_textarea,
		)

		st.text_area(
			"JSON Schema",
			key="json_text",
			height=380,
			help="Edit JSON then press Render Canvas.",
		)

		if st.button("Render Canvas", type="primary", use_container_width=True):
			parse_and_store_render_schema()

		st.divider()
		st.subheader("Add Current JSON as Sample")
		sample_name = st.text_input("Sample Name", placeholder="My custom sample")
		if st.button("Add to Samples", use_container_width=True):
			ok, message = add_current_json_as_sample(sample_name)
			if ok:
				st.success(message)
				load_selected_sample_into_textarea()
			else:
				st.error(message)

		if st.session_state.render_error:
			st.error(st.session_state.render_error)

	with right:
		st.subheader("Canvas")
		with st.container(border=True):
			render_canvas(st.session_state.rendered_schema)

		st.subheader("Current Parsed Schema")
		st.json(st.session_state.rendered_schema)

	if st.session_state.http_auto_poll and st.session_state.http_listener_running:
		time.sleep(int(st.session_state.http_poll_interval))
		st.rerun()


if __name__ == "__main__":
	app()
