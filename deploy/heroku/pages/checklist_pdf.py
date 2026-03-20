import os
import tempfile
import json

import streamlit as st
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

st.title('Checklist Form to PDF (Basic Test)')
st.caption('Simplified page for testing core functionality: build form, enter values, download unsigned PDF.')


def ensure_space(pdf_canvas, y_pos, needed_height, page_height):
    if y_pos - needed_height < 50:
        pdf_canvas.showPage()
        pdf_canvas.setFont('Helvetica', 12)
        return page_height - 50
    return y_pos


def render_components(components, key_prefix):
    values = {}
    for idx, component in enumerate(components):
        comp_type = component.get('type')
        label = component.get('label', f'Field {idx + 1}')
        if comp_type == 'Text':
            st.markdown(f'**{label}**')
        elif comp_type == 'Text Input':
            values[label] = st.text_input(label, key=f'{key_prefix}_text_{idx}')
        elif comp_type == 'Textarea':
            values[label] = st.text_area(label, key=f'{key_prefix}_textarea_{idx}')
        elif comp_type == 'Checkbox':
            values[label] = st.checkbox(
                label,
                value=component.get('default', False),
                key=f'{key_prefix}_checkbox_{idx}',
            )
        elif comp_type == 'Image Upload':
            values[label] = st.file_uploader(
                label,
                type=['png', 'jpg', 'jpeg'],
                key=f'{key_prefix}_image_{idx}',
            )
    return values


def build_pdf(form_name, components, values):
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = os.path.join(tmp_dir, 'checklist_output.pdf')
        pdf_canvas = canvas.Canvas(pdf_path, pagesize=letter)
        page_width, page_height = letter

        y_pos = page_height - 50
        pdf_canvas.setFont('Helvetica-Bold', 16)
        pdf_canvas.drawCentredString(page_width / 2, y_pos, f'Checklist Form: {form_name}')
        y_pos -= 35
        pdf_canvas.setFont('Helvetica', 12)

        for component in components:
            comp_type = component.get('type')
            label = component.get('label', '')

            if comp_type == 'Text':
                y_pos = ensure_space(pdf_canvas, y_pos, 20, page_height)
                pdf_canvas.drawString(50, y_pos, label)
                y_pos -= 20
            elif comp_type == 'Text Input':
                y_pos = ensure_space(pdf_canvas, y_pos, 20, page_height)
                pdf_canvas.drawString(50, y_pos, f"{label}: {values.get(label, '')}")
                y_pos -= 20
            elif comp_type == 'Textarea':
                y_pos = ensure_space(pdf_canvas, y_pos, 15, page_height)
                pdf_canvas.drawString(50, y_pos, f'{label}:')
                y_pos -= 15
                lines = (values.get(label, '') or '').split('\n')
                for line in lines:
                    y_pos = ensure_space(pdf_canvas, y_pos, 15, page_height)
                    pdf_canvas.drawString(70, y_pos, line)
                    y_pos -= 15
                y_pos -= 5
            elif comp_type == 'Checkbox':
                y_pos = ensure_space(pdf_canvas, y_pos, 20, page_height)
                checked = 'Yes' if values.get(label, False) else 'No'
                pdf_canvas.drawString(50, y_pos, f'{label}: {checked}')
                y_pos -= 20
            elif comp_type == 'Image Upload':
                uploaded_img = values.get(label)
                y_pos = ensure_space(pdf_canvas, y_pos, 20, page_height)
                pdf_canvas.drawString(50, y_pos, f'{label}:')
                y_pos -= 20

                if uploaded_img is None:
                    y_pos = ensure_space(pdf_canvas, y_pos, 15, page_height)
                    pdf_canvas.drawString(70, y_pos, '(no image uploaded)')
                    y_pos -= 20
                else:
                    try:
                        image = Image.open(uploaded_img)
                        img_width, img_height = image.size
                        if img_width > 0:
                            max_width = page_width - 120
                            display_width = min(max_width, float(img_width))
                            display_height = display_width * (float(img_height) / float(img_width))

                            y_pos = ensure_space(pdf_canvas, y_pos, display_height + 10, page_height)
                            pdf_canvas.drawImage(
                                ImageReader(image),
                                70,
                                y_pos - display_height,
                                width=display_width,
                                height=display_height,
                                preserveAspectRatio=True,
                                mask='auto',
                            )
                            y_pos -= display_height + 15
                    except Exception as exc:
                        y_pos = ensure_space(pdf_canvas, y_pos, 15, page_height)
                        pdf_canvas.drawString(70, y_pos, f'(image error: {exc})')
                        y_pos -= 20

        pdf_canvas.save()
        with open(pdf_path, 'rb') as pdf_file:
            return pdf_file.read()


def init_state():
    if 'forms' not in st.session_state:
        st.session_state.forms = {}
    if 'builder_components' not in st.session_state:
        st.session_state.builder_components = []
    if 'builder_form_name' not in st.session_state:
        st.session_state.builder_form_name = ''

    if 'temp_form_counter' not in st.session_state:
        st.session_state.temp_form_counter = 1

    if not st.session_state.builder_form_name:
        temp_name = f"temp_form_{st.session_state.temp_form_counter}"
        st.session_state.temp_form_counter += 1
        st.session_state.forms[temp_name] = {'components': []}
        st.session_state.builder_form_name = temp_name
        st.session_state.builder_components = []


def load_builder_from_form(form_name):
    form = st.session_state.forms.get(form_name)
    if form:
        st.session_state.builder_components = list(form.get('components', []))
        st.session_state.builder_form_name = form_name


def parse_imported_form(file_data):
    payload = json.loads(file_data.decode('utf-8'))
    if not isinstance(payload, dict):
        raise ValueError('Imported JSON must be an object.')

    components = payload.get('components')
    if not isinstance(components, list):
        raise ValueError('Imported JSON must include a components array.')

    allowed_types = {'Text', 'Text Input', 'Textarea', 'Checkbox', 'Image Upload'}
    cleaned = []
    for item in components:
        if not isinstance(item, dict):
            raise ValueError('Each component must be an object.')
        comp_type = item.get('type')
        label = item.get('label')
        if comp_type not in allowed_types:
            raise ValueError(f'Unsupported component type: {comp_type}')
        if not isinstance(label, str) or not label.strip():
            raise ValueError('Each component must include a non-empty label.')

        entry = {'type': comp_type, 'label': label.strip()}
        if comp_type == 'Checkbox':
            entry['default'] = bool(item.get('default', False))
        cleaned.append(entry)

    imported_name = payload.get('name', '')
    if not isinstance(imported_name, str):
        imported_name = ''

    return imported_name.strip(), cleaned


init_state()

active_form_name = st.session_state.builder_form_name
if 'pending_save_form_name' in st.session_state:
    st.session_state.save_form_name = st.session_state.pending_save_form_name
    del st.session_state.pending_save_form_name
if st.session_state.get('save_form_name') != active_form_name:
    st.session_state.save_form_name = active_form_name

builder_tab, render_tab = st.tabs(['Form Builder', 'Render and Export'])

with builder_tab:
    st.subheader('Form Builder')

    form_names = list(st.session_state.forms.keys())
    if active_form_name not in form_names:
        form_names = [active_form_name] + form_names

    selected_builder_form = st.selectbox(
        'Select form to build',
        form_names,
        index=form_names.index(active_form_name),
        key='builder_form_select',
    )

    if selected_builder_form != st.session_state.builder_form_name:
        load_builder_from_form(selected_builder_form)
        st.session_state.pending_save_form_name = selected_builder_form

    active_form_name = st.session_state.builder_form_name
    st.write(f'Active form: {active_form_name}')

    new_name = st.text_input('Create new form', key='new_form_name')
    if st.button('Use New Form'):
        if not new_name.strip():
            st.error('Please enter a form name.')
        else:
            st.session_state.builder_form_name = new_name.strip()
            st.session_state.builder_components = []
            st.session_state.pending_save_form_name = new_name.strip()
            st.success(f'Editing new form: {new_name.strip()}')

    component_type = st.selectbox('Component type', ['Text', 'Text Input', 'Textarea', 'Checkbox', 'Image Upload'])
    component_label = st.text_input('Component label', key='builder_component_label')
    checkbox_default = st.checkbox('Default checked', key='builder_checkbox_default') if component_type == 'Checkbox' else False
    save_form_name = st.text_input('Form name to save', key='save_form_name')

    if st.button('Add Component'):
        if not component_label.strip():
            st.error('Component label is required.')
        else:
            entry = {'type': component_type, 'label': component_label.strip()}
            if component_type == 'Checkbox':
                entry['default'] = checkbox_default
            st.session_state.builder_components.append(entry)
            st.success(f'Added {component_type}: {component_label.strip()}')

    if st.button('Save Form'):
        target_name = save_form_name.strip()
        if not target_name:
            st.error('Enter a form name to save.')
        else:
            previous_name = active_form_name
            st.session_state.forms[target_name] = {'components': list(st.session_state.builder_components)}

            if previous_name != target_name and previous_name.startswith('temp_form_'):
                st.session_state.forms.pop(previous_name, None)

            st.session_state.builder_form_name = target_name
            st.success(f'Saved form: {target_name}')

    if st.session_state.builder_components:
        st.write('Current components:')
        for index, component in enumerate(st.session_state.builder_components, start=1):
            if component['type'] == 'Checkbox':
                st.write(f"{index}. [{component['type']}] {component['label']} (default={component.get('default', False)})")
            else:
                st.write(f"{index}. [{component['type']}] {component['label']}")

        st.markdown('---')
        st.write('Edit / Delete / Reorder Components')

        component_options = [
            f"{idx + 1}. [{item.get('type')}] {item.get('label', '')}"
            for idx, item in enumerate(st.session_state.builder_components)
        ]
        selected_component_label = st.selectbox('Select component', component_options, key='manage_component_select')
        selected_idx = component_options.index(selected_component_label)
        selected_component = st.session_state.builder_components[selected_idx]

        edit_label = st.text_input(
            'Edit label',
            value=selected_component.get('label', ''),
            key=f'edit_component_label_{selected_idx}',
        )
        edit_default = False
        if selected_component.get('type') == 'Checkbox':
            edit_default = st.checkbox(
                'Checkbox default',
                value=selected_component.get('default', False),
                key=f'edit_component_default_{selected_idx}',
            )

        action_cols = st.columns(4)
        with action_cols[0]:
            if st.button('Update Component'):
                if not edit_label.strip():
                    st.error('Label cannot be empty.')
                else:
                    st.session_state.builder_components[selected_idx]['label'] = edit_label.strip()
                    if selected_component.get('type') == 'Checkbox':
                        st.session_state.builder_components[selected_idx]['default'] = edit_default
                    st.success('Component updated.')
        with action_cols[1]:
            if st.button('Delete Component'):
                st.session_state.builder_components.pop(selected_idx)
                st.success('Component deleted.')
        with action_cols[2]:
            if st.button('Move Up') and selected_idx > 0:
                comps = st.session_state.builder_components
                comps[selected_idx - 1], comps[selected_idx] = comps[selected_idx], comps[selected_idx - 1]
                st.success('Component moved up.')
        with action_cols[3]:
            if st.button('Move Down') and selected_idx < len(st.session_state.builder_components) - 1:
                comps = st.session_state.builder_components
                comps[selected_idx + 1], comps[selected_idx] = comps[selected_idx], comps[selected_idx + 1]
                st.success('Component moved down.')

    st.markdown('---')
    st.write('Export / Import Form Definition')

    export_form_name = st.session_state.save_form_name.strip() or active_form_name
    export_payload = {
        'name': export_form_name,
        'components': list(st.session_state.builder_components),
    }
    st.download_button(
        'Export Form JSON',
        data=json.dumps(export_payload, indent=2).encode('utf-8'),
        file_name=f'{export_form_name}.json',
        mime='application/json',
    )

    import_file = st.file_uploader('Import form JSON', type=['json'], key='import_form_json')
    import_target_name = st.text_input('Imported form name override (optional)', key='import_form_name_override')
    if st.button('Import Form'):
        if import_file is None:
            st.error('Choose a JSON file to import.')
        else:
            try:
                imported_name, imported_components = parse_imported_form(import_file.getvalue())
                target_name = import_target_name.strip() or imported_name or f"temp_form_{st.session_state.temp_form_counter}"
                if target_name.startswith('temp_form_') and target_name not in st.session_state.forms:
                    st.session_state.temp_form_counter += 1
                st.session_state.forms[target_name] = {'components': imported_components}
                load_builder_from_form(target_name)
                st.session_state.pending_save_form_name = target_name
                st.success(f'Imported form: {target_name}')
            except Exception as exc:
                st.error(f'Import failed: {exc}')

with render_tab:
    st.subheader('Render and Export')

    if not st.session_state.builder_components:
        st.info('Add at least one component in Form Builder to preview and export.')
    else:
        st.write('Live preview of the current form you are building:')
        live_values = render_components(st.session_state.builder_components, 'live_render')

        export_name = st.session_state.save_form_name.strip() or active_form_name
        if st.button('Generate PDF from Current Form'):
            pdf_data = build_pdf(export_name, st.session_state.builder_components, live_values)
            st.success('PDF generated from current form data.')
            st.download_button(
                'Download PDF',
                data=pdf_data,
                file_name=f'{export_name}_basic.pdf',
                mime='application/pdf',
            )
