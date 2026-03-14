from pathlib import Path
import re
import textwrap

import streamlit as st


FIELD_TEMPLATES = {
	"text_input": {
		"label": "Text Input",
		"key": "text_input",
		"placeholder": "",
		"help_text": "",
		"required": False,
	},
	"text_area": {
		"label": "Text Area",
		"key": "text_area",
		"placeholder": "",
		"help_text": "",
		"required": False,
	},
	"number_input": {
		"label": "Number Input",
		"key": "number_input",
		"min_value": 0,
		"max_value": 100,
		"value": 0,
		"step": 1,
		"help_text": "",
		"required": False,
	},
	"selectbox": {
		"label": "Select Box",
		"key": "selectbox",
		"options": ["Option 1", "Option 2", "Option 3"],
		"help_text": "",
		"required": False,
	},
	"checkbox": {
		"label": "Checkbox",
		"key": "checkbox",
		"value": False,
		"help_text": "",
		"required": False,
	},
}

APP_DIR = Path(__file__).resolve().parent
PUBLISH_DIR = APP_DIR


def slugify(value: str) -> str:
	cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
	return cleaned or "generated_form_app"


def ensure_state() -> None:
	st.session_state.setdefault("builder_title", "Custom Form Builder")
	st.session_state.setdefault("builder_description", "Complete the fields below and submit the form.")
	st.session_state.setdefault("builder_submit_label", "Submit")
	st.session_state.setdefault("builder_filename", "generated_form_app")
	st.session_state.setdefault("builder_fields", [])


def next_field_name(field_type: str) -> str:
	count = sum(1 for field in st.session_state.builder_fields if field["type"] == field_type)
	return f"{field_type}_{count + 1}"


def add_field(field_type: str) -> None:
	template = FIELD_TEMPLATES[field_type].copy()
	template["type"] = field_type
	template["id"] = next_field_name(field_type)
	st.session_state.builder_fields.append(template)


def move_field(index: int, direction: int) -> None:
	new_index = index + direction
	fields = st.session_state.builder_fields
	if 0 <= new_index < len(fields):
		fields[index], fields[new_index] = fields[new_index], fields[index]


def delete_field(index: int) -> None:
	st.session_state.builder_fields.pop(index)


def render_field_editor(index: int, field: dict) -> None:
	title = f"{index + 1}. {field['label']} ({field['type']})"
	with st.expander(title, expanded=index == 0):
		field["label"] = st.text_input("Label", value=field["label"], key=f"label_{field['id']}")
		field["key"] = slugify(
			st.text_input("Field Key", value=field["key"], key=f"key_{field['id']}")
		)
		field["help_text"] = st.text_input(
			"Help Text", value=field.get("help_text", ""), key=f"help_{field['id']}"
		)
		field["required"] = st.checkbox(
			"Required", value=field.get("required", False), key=f"required_{field['id']}"
		)

		if field["type"] in {"text_input", "text_area"}:
			field["placeholder"] = st.text_input(
				"Placeholder",
				value=field.get("placeholder", ""),
				key=f"placeholder_{field['id']}",
			)

		if field["type"] == "number_input":
			min_value = st.number_input(
				"Minimum", value=int(field.get("min_value", 0)), key=f"min_{field['id']}"
			)
			max_value = st.number_input(
				"Maximum", value=int(field.get("max_value", 100)), key=f"max_{field['id']}"
			)
			step = st.number_input(
				"Step", min_value=1, value=int(field.get("step", 1)), key=f"step_{field['id']}"
			)
			current_value = int(field.get("value", 0))
			lower = int(min(min_value, max_value))
			upper = int(max(min_value, max_value))
			field["min_value"] = lower
			field["max_value"] = upper
			field["step"] = int(step)
			field["value"] = min(max(current_value, lower), upper)

		if field["type"] == "selectbox":
			options_text = st.text_area(
				"Options (one per line)",
				value="\n".join(field.get("options", [])),
				key=f"options_{field['id']}",
			)
			options = [line.strip() for line in options_text.splitlines() if line.strip()]
			field["options"] = options or ["Option 1"]

		if field["type"] == "checkbox":
			field["value"] = st.checkbox(
				"Checked by default", value=field.get("value", False), key=f"checked_{field['id']}"
			)

		action_cols = st.columns(3)
		with action_cols[0]:
			if st.button("Move Up", key=f"up_{field['id']}", use_container_width=True):
				move_field(index, -1)
				st.rerun()
		with action_cols[1]:
			if st.button("Move Down", key=f"down_{field['id']}", use_container_width=True):
				move_field(index, 1)
				st.rerun()
		with action_cols[2]:
			if st.button("Remove", key=f"remove_{field['id']}", use_container_width=True):
				delete_field(index)
				st.rerun()


def render_preview_field(field: dict) -> None:
	label = field["label"] + (" *" if field.get("required") else "")
	help_text = field.get("help_text") or None

	if field["type"] == "text_input":
		st.text_input(label, placeholder=field.get("placeholder", ""), help=help_text, disabled=True)
	elif field["type"] == "text_area":
		st.text_area(label, placeholder=field.get("placeholder", ""), help=help_text, disabled=True)
	elif field["type"] == "number_input":
		st.number_input(
			label,
			min_value=int(field.get("min_value", 0)),
			max_value=int(field.get("max_value", 100)),
			value=int(field.get("value", 0)),
			step=int(field.get("step", 1)),
			help=help_text,
			disabled=True,
		)
	elif field["type"] == "selectbox":
		st.selectbox(label, options=field.get("options", ["Option 1"]), help=help_text, disabled=True)
	elif field["type"] == "checkbox":
		st.checkbox(label, value=field.get("value", False), help=help_text, disabled=True)


def generate_field_code(field: dict) -> str:
	label_expr = repr(field["label"] + (" *" if field.get("required") else ""))
	key_expr = repr(field["key"])
	help_expr = repr(field.get("help_text", ""))

	if field["type"] == "text_input":
		return (
			f"    submitted_data[{key_expr}] = st.text_input({label_expr}, "
			f"placeholder={repr(field.get('placeholder', ''))}, help={help_expr})"
		)
	if field["type"] == "text_area":
		return (
			f"    submitted_data[{key_expr}] = st.text_area({label_expr}, "
			f"placeholder={repr(field.get('placeholder', ''))}, help={help_expr})"
		)
	if field["type"] == "number_input":
		return (
			f"    submitted_data[{key_expr}] = st.number_input({label_expr}, "
			f"min_value={int(field.get('min_value', 0))}, max_value={int(field.get('max_value', 100))}, "
			f"value={int(field.get('value', 0))}, step={int(field.get('step', 1))}, help={help_expr})"
		)
	if field["type"] == "selectbox":
		return (
			f"    submitted_data[{key_expr}] = st.selectbox({label_expr}, "
			f"options={repr(field.get('options', ['Option 1']))}, help={help_expr})"
		)
	return f"    submitted_data[{key_expr}] = st.checkbox({label_expr}, value={bool(field.get('value', False))}, help={help_expr})"


def generate_app_source(title: str, description: str, submit_label: str, fields: list[dict]) -> str:
	field_code = "\n".join(generate_field_code(field) for field in fields) or "    st.info('No fields configured.')"
	return textwrap.dedent(
		f'''
		import streamlit as st


		def app() -> None:
			st.set_page_config(page_title={title!r})
			st.title({title!r})
			st.write({description!r})

			submitted_data = {{}}
			with st.form("published_form"):
		{field_code}
				submitted = st.form_submit_button({submit_label!r})

			if submitted:
				st.success("Form submitted successfully.")
				st.json(submitted_data)


		if __name__ == "__main__":
			app()
		'''
	).strip() + "\n"


def publish_app(title: str, description: str, submit_label: str, filename: str, fields: list[dict]) -> Path:
	target_path = PUBLISH_DIR / f"{slugify(filename)}.py"
	source = generate_app_source(title, description, submit_label, fields)
	target_path.write_text(source, encoding="utf-8")
	return target_path


def app() -> None:
	st.set_page_config(page_title="Streamlit App Maker", layout="wide")
	ensure_state()

	st.title("Streamlit App Maker")
	st.write("Build a form visually, preview it on the canvas, and publish it as a runnable Streamlit page.")

	settings_col, canvas_col = st.columns([1, 1.3], gap="large")

	with settings_col:
		st.subheader("App Settings")
		st.session_state.builder_title = st.text_input("App Title", value=st.session_state.builder_title)
		st.session_state.builder_description = st.text_area(
			"App Description", value=st.session_state.builder_description, height=100
		)
		st.session_state.builder_submit_label = st.text_input(
			"Submit Button Label", value=st.session_state.builder_submit_label
		)
		st.session_state.builder_filename = slugify(
			st.text_input("Published File Name", value=st.session_state.builder_filename)
		)

		st.subheader("Add Elements")
		add_cols = st.columns(len(FIELD_TEMPLATES))
		for column, field_type in zip(add_cols, FIELD_TEMPLATES):
			with column:
				label = FIELD_TEMPLATES[field_type]["label"]
				if st.button(label, key=f"add_{field_type}", use_container_width=True):
					add_field(field_type)
					st.rerun()

		st.subheader("Canvas Elements")
		if not st.session_state.builder_fields:
			st.info("Add a field to start building the form.")
		else:
			for index, field in enumerate(st.session_state.builder_fields):
				render_field_editor(index, field)

	with canvas_col:
		st.subheader("Canvas Preview")
		with st.container(border=True):
			st.markdown(f"### {st.session_state.builder_title}")
			st.write(st.session_state.builder_description)

			if not st.session_state.builder_fields:
				st.caption("Your form preview will appear here.")
			else:
				with st.form("preview_form"):
					for field in st.session_state.builder_fields:
						render_preview_field(field)
					st.form_submit_button(st.session_state.builder_submit_label, disabled=True)

		source = generate_app_source(
			st.session_state.builder_title,
			st.session_state.builder_description,
			st.session_state.builder_submit_label,
			st.session_state.builder_fields,
		)
		st.subheader("Generated Source")
		st.code(source, language="python")

		publish_cols = st.columns([1, 1])
		with publish_cols[0]:
			if st.button("Publish App", type="primary", use_container_width=True):
				target = publish_app(
					st.session_state.builder_title,
					st.session_state.builder_description,
					st.session_state.builder_submit_label,
					st.session_state.builder_filename,
					st.session_state.builder_fields,
				)
				st.success(f"Published app to {target.name}")
		with publish_cols[1]:
			st.download_button(
				"Download Source",
				data=source,
				file_name=f"{st.session_state.builder_filename}.py",
				mime="text/x-python",
				use_container_width=True,
			)


if __name__ == "__main__":
	app()
