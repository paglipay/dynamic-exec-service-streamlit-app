import json
import re
from copy import deepcopy
from datetime import date, datetime
from urllib import error, parse, request

import streamlit as st
from _ai_assistant_panel import render_ai_assistant_panel


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


def assistant_context_payload() -> dict:
	json_text = st.session_state.get("json_text", "")
	parsed_json = None
	json_parse_error = ""

	if json_text:
		try:
			parsed_json = json.loads(json_text)
		except json.JSONDecodeError as exc:
			json_parse_error = str(exc)

	return {
		"selected_sample_name": st.session_state.get("selected_sample_name", ""),
		"json_editor_text": json_text,
		"json_editor_parsed": parsed_json,
		"json_editor_parse_error": json_parse_error,
		"rendered_schema": st.session_state.get("rendered_schema"),
		"render_error": st.session_state.get("render_error", ""),
	}


def extract_schema_from_ai_message(message: str) -> tuple[dict | None, str]:
	candidates: list[str] = []

	for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", message, flags=re.IGNORECASE):
		block = match.group(1).strip()
		if block:
			candidates.append(block)

	cleaned_message = message.strip()
	if cleaned_message:
		candidates.append(cleaned_message)

	for candidate in candidates:
		try:
			parsed = json.loads(candidate)
		except json.JSONDecodeError:
			continue

		valid, reason = validate_schema(parsed)
		if valid:
			return parsed, ""
		return None, f"AI JSON is invalid schema: {reason}"

	return None, "No valid JSON schema found in the assistant response."


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
	ai_messages_key = "ai_messages_Dynamic JSON Canvas"
	render_ai_assistant_panel(
		"Dynamic JSON Canvas",
		context_data=assistant_context_payload(),
		prefer_json_schema=True,
	)

	st.title("Dynamic JSON Canvas Renderer")
	st.write("Pick a sample JSON, edit it, and press Render Canvas to quickly update the canvas.")

	left, right = st.columns([1, 1.4], gap="large")

	with left:
		st.subheader("JSON Editor")

		if st.button("Apply Latest AI Schema", use_container_width=True):
			messages = st.session_state.get(ai_messages_key, [])
			last_assistant = next(
				(
					msg.get("content", "")
					for msg in reversed(messages)
					if msg.get("role") == "assistant"
				),
				"",
			)
			if not last_assistant:
				st.error("No assistant response found yet.")
			else:
				parsed_schema, reason = extract_schema_from_ai_message(last_assistant)
				if parsed_schema is None:
					st.error(reason)
				else:
					st.session_state.json_text = to_json_text(parsed_schema)
					parse_and_store_render_schema()
					if st.session_state.render_error:
						st.error(st.session_state.render_error)
					else:
						st.success("Applied JSON schema from assistant.")

		st.caption(
			"Tip: ask the assistant to return a full schema JSON, then click Apply Latest AI Schema."
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


if __name__ == "__main__":
	app()
