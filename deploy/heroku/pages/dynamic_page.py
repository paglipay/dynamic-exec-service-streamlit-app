import json
from copy import deepcopy

import streamlit as st


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
				{"type": "button", "label": "Send Message"}
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
				{"type": "checkbox", "label": "Blocks release", "key": "blocks_release", "value": False}
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
				{"type": "date_input", "label": "Arrival Date", "key": "arrival_date"}
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
				{"type": "checkbox", "label": "Urgent", "key": "urgent", "value": True}
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
				{"type": "text_area", "label": "Preferences", "key": "preferences"}
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
				{"type": "selectbox", "label": "Impact", "key": "impact", "options": ["Small", "Medium", "Large"]}
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
				{"type": "text_area", "label": "Feedback", "key": "feedback"}
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
				{"type": "checkbox", "label": "Need Help", "key": "need_help", "value": False}
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
				{"type": "checkbox", "label": "Backordered", "key": "backordered", "value": False}
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
				{"type": "button", "label": "Register"}
			]
		},
	},
]


BUILDER_TEMPLATES = {
	"text_input": {"type": "text_input", "label": "Text Input", "key": "text_input", "placeholder": ""},
	"text_area": {"type": "text_area", "label": "Text Area", "key": "text_area", "placeholder": ""},
	"number_input": {
		"type": "number_input",
		"label": "Number Input",
		"key": "number_input",
		"min_value": 0,
		"max_value": 100,
		"value": 0,
		"step": 1,
	},
	"selectbox": {
		"type": "selectbox",
		"label": "Select Box",
		"key": "selectbox",
		"options": ["Option 1", "Option 2", "Option 3"],
	},
	"checkbox": {"type": "checkbox", "label": "Checkbox", "key": "checkbox", "value": False},
	"button": {"type": "button", "label": "Submit"},
}


def to_json_text(schema: dict) -> str:
	return json.dumps(schema, indent=2)


def normalize_key(raw_key: str, fallback: str) -> str:
	key = (raw_key or "").strip().lower().replace(" ", "_")
	return key or fallback


def ensure_schema_shape(schema: dict) -> dict:
	ensured = deepcopy(schema) if isinstance(schema, dict) else {}
	if not isinstance(ensured.get("elements"), list):
		ensured["elements"] = []
	if "title" not in ensured:
		ensured["title"] = "Dynamic Canvas"
	if "description" not in ensured:
		ensured["description"] = ""
	return ensured


def init_state() -> None:
	if "samples" not in st.session_state:
		st.session_state.samples = deepcopy(DEFAULT_SAMPLES)

	if "selected_sample_name" not in st.session_state:
		st.session_state.selected_sample_name = st.session_state.samples[0]["name"]

	if "json_text" not in st.session_state:
		st.session_state.json_text = to_json_text(st.session_state.samples[0]["schema"])

	if "rendered_schema" not in st.session_state:
		st.session_state.rendered_schema = ensure_schema_shape(st.session_state.samples[0]["schema"])

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
	schema = ensure_schema_shape(selected["schema"])
	st.session_state.json_text = to_json_text(schema)
	st.session_state.rendered_schema = schema


def sync_json_from_rendered_schema() -> None:
	st.session_state.json_text = to_json_text(st.session_state.rendered_schema)


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
		if element["type"] != "button" and "key" not in element:
			return False, f"Element #{idx + 1} is missing 'key'."

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


def next_builder_name(elements: list[dict], element_type: str) -> int:
	return sum(1 for element in elements if element.get("type") == element_type) + 1


def add_builder_element(element_type: str) -> None:
	template = deepcopy(BUILDER_TEMPLATES[element_type])
	elements = st.session_state.rendered_schema.get("elements", [])
	number = next_builder_name(elements, element_type)
	template["label"] = f"{template['label']} {number}" if element_type != "button" else f"{template['label']} {number}"
	if "key" in template:
		template["key"] = normalize_key(f"{template['key']}_{number}", f"field_{number}")
	elements.append(template)
	st.session_state.rendered_schema["elements"] = elements
	sync_json_from_rendered_schema()


def remove_builder_element(index: int) -> None:
	elements = st.session_state.rendered_schema.get("elements", [])
	if 0 <= index < len(elements):
		elements.pop(index)
		st.session_state.rendered_schema["elements"] = elements
		sync_json_from_rendered_schema()


def render_builder() -> None:
	schema = st.session_state.rendered_schema
	original_schema = deepcopy(schema)
	schema["title"] = st.text_input("Canvas Title", value=schema.get("title", "Dynamic Canvas"), key="builder_title")
	schema["description"] = st.text_area(
		"Canvas Description",
		value=schema.get("description", ""),
		height=80,
		key="builder_description",
	)

	add_cols = st.columns(len(BUILDER_TEMPLATES))
	for col, element_type in zip(add_cols, BUILDER_TEMPLATES):
		with col:
			if st.button(f"Add {element_type}", key=f"add_builder_{element_type}", use_container_width=True):
				add_builder_element(element_type)
				st.rerun()

	elements = schema.get("elements", [])
	updated_elements: list[dict] = []

	for idx, element in enumerate(elements):
		elem = deepcopy(element)
		elem_type = elem.get("type", "text_input")
		with st.expander(f"{idx + 1}. {elem_type}", expanded=False):
			elem["type"] = st.selectbox(
				"Type",
				options=list(BUILDER_TEMPLATES.keys()),
				index=list(BUILDER_TEMPLATES.keys()).index(elem_type) if elem_type in BUILDER_TEMPLATES else 0,
				key=f"builder_type_{idx}",
			)
			elem["label"] = st.text_input("Label", value=elem.get("label", ""), key=f"builder_label_{idx}")

			if elem["type"] != "button":
				elem["key"] = normalize_key(
					st.text_input("Key", value=elem.get("key", f"field_{idx + 1}"), key=f"builder_key_{idx}"),
					f"field_{idx + 1}",
				)

			if elem["type"] in {"text_input", "text_area"}:
				elem["placeholder"] = st.text_input(
					"Placeholder",
					value=elem.get("placeholder", ""),
					key=f"builder_placeholder_{idx}",
				)

			if elem["type"] == "number_input":
				elem["min_value"] = st.number_input("Min", value=int(elem.get("min_value", 0)), key=f"builder_min_{idx}")
				elem["max_value"] = st.number_input("Max", value=int(elem.get("max_value", 100)), key=f"builder_max_{idx}")
				elem["value"] = st.number_input("Value", value=int(elem.get("value", 0)), key=f"builder_value_{idx}")
				elem["step"] = st.number_input("Step", min_value=1, value=int(elem.get("step", 1)), key=f"builder_step_{idx}")

			if elem["type"] == "selectbox":
				options_text = st.text_area(
					"Options (one per line)",
					value="\n".join(elem.get("options", ["Option 1"])),
					key=f"builder_options_{idx}",
				)
				elem["options"] = [line.strip() for line in options_text.splitlines() if line.strip()] or ["Option 1"]

			if elem["type"] == "checkbox":
				elem["value"] = st.checkbox("Default Checked", value=bool(elem.get("value", False)), key=f"builder_checked_{idx}")

			if st.button("Remove Element", key=f"builder_remove_{idx}", use_container_width=True):
				remove_builder_element(idx)
				st.rerun()

		updated_elements.append(elem)

	schema["elements"] = updated_elements
	st.session_state.rendered_schema = schema
	if schema != original_schema:
		sync_json_from_rendered_schema()


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


def render_dynamic_element(element: dict, idx: int, used_keys: set[str]) -> None:
	elem_type = element.get("type", "")
	key = normalize_key(element.get("key", ""), f"field_{idx + 1}")
	if key in used_keys:
		key = f"{key}_{idx + 1}"
	used_keys.add(key)

	label = element.get("label", key)
	help_text = element.get("help", None)

	if elem_type == "header":
		st.header(element.get("text", label))
		return
	if elem_type == "subheader":
		st.subheader(element.get("text", label))
		return
	if elem_type == "markdown":
		st.markdown(element.get("text", ""))
		return
	if elem_type == "text_input":
		st.text_input(label, key=key, placeholder=element.get("placeholder", ""), help=help_text)
		return
	if elem_type == "text_area":
		st.text_area(label, key=key, placeholder=element.get("placeholder", ""), help=help_text)
		return
	if elem_type == "number_input":
		st.number_input(
			label,
			key=key,
			min_value=element.get("min_value", 0),
			max_value=element.get("max_value", 100),
			value=element.get("value", 0),
			step=element.get("step", 1),
			help=help_text,
		)
		return
	if elem_type == "selectbox":
		st.selectbox(label, options=element.get("options", ["Option 1"]), key=key, help=help_text)
		return
	if elem_type == "checkbox":
		st.checkbox(label, value=element.get("value", False), key=key, help=help_text)
		return
	if elem_type == "slider":
		st.slider(
			label,
			min_value=element.get("min_value", 0),
			max_value=element.get("max_value", 100),
			value=element.get("value", 25),
			key=key,
			help=help_text,
		)
		return
	if elem_type == "date_input":
		st.date_input(label, key=key, help=help_text)
		return
	if elem_type == "button":
		return

	st.warning(f"Unsupported element type: {elem_type}")


def render_canvas(schema: dict) -> None:
	st.markdown(f"### {schema.get('title', 'Dynamic Canvas')}")
	if schema.get("description"):
		st.caption(schema["description"])

	used_keys: set[str] = set()
	button_labels: list[str] = []
	with st.form("dynamic_canvas_form"):
		for idx, element in enumerate(schema.get("elements", [])):
			if element.get("type") == "button":
				button_labels.append(element.get("label", "Submit"))
				continue
			render_dynamic_element(element, idx, used_keys)

		submitted = False
		for idx, button_label in enumerate(button_labels):
			if st.form_submit_button(button_label, use_container_width=True):
				submitted = True

	if button_labels and submitted:
		st.success("Form submitted.")
	elif not button_labels:
		st.info("Add an element with type 'button' to enable form submission.")


def app() -> None:
	st.set_page_config(page_title="Dynamic JSON Canvas", layout="wide")
	init_state()

	st.title("Dynamic JSON Canvas Renderer")
	st.write("Pick a sample JSON, edit it, and press Render Canvas to quickly update the canvas.")

	left, right = st.columns([1, 1.4], gap="large")

	with left:
		st.subheader("JSON Editor")

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
		st.subheader("Visual Form Builder")
		render_builder()

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
