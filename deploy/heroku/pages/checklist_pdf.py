import os
import tempfile
import json
from io import BytesIO

import streamlit as st
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from _auth_guard import require_authentication
try:
    from pdf2image import convert_from_bytes
except ImportError:
    convert_from_bytes = None

try:
    from streamlit_js_eval import streamlit_js_eval
except ImportError:
    streamlit_js_eval = None

require_authentication('Checklist Form to PDF')
st.title('Checklist Form to PDF (Basic Test)')
st.caption('Simplified page for testing core functionality: build form, enter values, download unsigned PDF.')


def trigger_rerun():
    if hasattr(st, 'rerun'):
        st.rerun()
    elif hasattr(st, 'experimental_rerun'):
        st.experimental_rerun()


def ensure_space(pdf_canvas, y_pos, needed_height, page_height):
    if y_pos - needed_height < 50:
        pdf_canvas.showPage()
        pdf_canvas.setFont('Helvetica', 12)
        return page_height - 50
    return y_pos


def wrap_text(text, font_name, font_size, max_width):
    """Word-wrap text into lines that each fit within max_width points."""
    words = (text or '').split(' ')
    lines = []
    current_line = ''
    for word in words:
        candidate = f'{current_line} {word}'.strip() if current_line else word
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current_line = candidate
        else:
            if current_line:
                lines.append(current_line)
            # Force-break a single word that is wider than max_width
            if stringWidth(word, font_name, font_size) > max_width:
                partial = ''
                for ch in word:
                    if stringWidth(partial + ch, font_name, font_size) <= max_width:
                        partial += ch
                    else:
                        if partial:
                            lines.append(partial)
                        partial = ch
                current_line = partial
            else:
                current_line = word
    if current_line:
        lines.append(current_line)
    return lines if lines else ['']


def draw_wrapped(pdf_canvas, x, y, text, font_name, font_size, max_width, line_height, page_height):
    """Draw word-wrapped text, returning the updated y position."""
    for line in wrap_text(text, font_name, font_size, max_width):
        y = ensure_space(pdf_canvas, y, line_height, page_height)
        pdf_canvas.drawString(x, y, line)
        y -= line_height
    return y


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
        elif comp_type == 'Camera Input':
            values[label] = st.camera_input(
                label,
                key=f'{key_prefix}_camera_{idx}',
            )
    return values


def build_pdf(form_name, components, values):
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = os.path.join(tmp_dir, 'checklist_output.pdf')
        pdf_canvas = canvas.Canvas(pdf_path, pagesize=letter)
        page_width, page_height = letter

        # Margins: 50pt left, 50pt right
        left_margin = 50
        indent = 70
        right_margin = 50
        body_max_w = page_width - left_margin - right_margin   # 512 pt
        indent_max_w = page_width - indent - right_margin      # 492 pt
        line_h = 15

        y_pos = page_height - 50
        pdf_canvas.setFont('Helvetica-Bold', 16)
        # Wrap long form titles in the header
        for title_line in wrap_text(f'Checklist Form: {form_name}', 'Helvetica-Bold', 16, body_max_w):
            pdf_canvas.drawCentredString(page_width / 2, y_pos, title_line)
            y_pos -= 22
        y_pos -= 10
        pdf_canvas.setFont('Helvetica', 12)

        for component in components:
            comp_type = component.get('type')
            label = component.get('label', '')

            if comp_type == 'Text':
                pdf_canvas.setFont('Helvetica-Bold', 12)
                y_pos = draw_wrapped(pdf_canvas, left_margin, y_pos, label,
                                     'Helvetica-Bold', 12, body_max_w, line_h, page_height)
                pdf_canvas.setFont('Helvetica', 12)
                y_pos -= 4

            elif comp_type == 'Text Input':
                # Draw "Label:" on its own line, then the value indented
                y_pos = draw_wrapped(pdf_canvas, left_margin, y_pos, f'{label}:',
                                     'Helvetica', 12, body_max_w, line_h, page_height)
                value_text = values.get(label, '') or ''
                y_pos = draw_wrapped(pdf_canvas, indent, y_pos, value_text,
                                     'Helvetica', 12, indent_max_w, line_h, page_height)
                y_pos -= 4

            elif comp_type == 'Textarea':
                y_pos = draw_wrapped(pdf_canvas, left_margin, y_pos, f'{label}:',
                                     'Helvetica', 12, body_max_w, line_h, page_height)
                raw_lines = (values.get(label, '') or '').split('\n')
                for raw_line in raw_lines:
                    y_pos = draw_wrapped(pdf_canvas, indent, y_pos, raw_line,
                                        'Helvetica', 12, indent_max_w, line_h, page_height)
                y_pos -= 8

            elif comp_type == 'Checkbox':
                checked = 'Yes' if values.get(label, False) else 'No'
                y_pos = draw_wrapped(pdf_canvas, left_margin, y_pos, f'{label}: {checked}',
                                     'Helvetica', 12, body_max_w, line_h, page_height)
                y_pos -= 4

            elif comp_type in ('Image Upload', 'Camera Input'):
                uploaded_img = values.get(label)
                y_pos = draw_wrapped(pdf_canvas, left_margin, y_pos, f'{label}:',
                                     'Helvetica', 12, body_max_w, line_h, page_height)

                if uploaded_img is None:
                    y_pos = draw_wrapped(pdf_canvas, indent, y_pos, '(no image uploaded)',
                                        'Helvetica', 12, indent_max_w, line_h, page_height)
                else:
                    try:
                        image = Image.open(uploaded_img)
                        img_width, img_height = image.size
                        if img_width > 0:
                            max_img_w = page_width - indent - right_margin
                            display_width = min(max_img_w, float(img_width))
                            display_height = display_width * (float(img_height) / float(img_width))

                            y_pos = ensure_space(pdf_canvas, y_pos, display_height + 10, page_height)
                            pdf_canvas.drawImage(
                                ImageReader(image),
                                indent,
                                y_pos - display_height,
                                width=display_width,
                                height=display_height,
                                preserveAspectRatio=True,
                                mask='auto',
                            )
                            y_pos -= display_height + 15
                    except Exception as exc:
                        y_pos = draw_wrapped(pdf_canvas, indent, y_pos, f'(image error: {exc})',
                                            'Helvetica', 12, indent_max_w, line_h, page_height)
                y_pos -= 4

        pdf_canvas.save()
        with open(pdf_path, 'rb') as pdf_file:
            return pdf_file.read()


def pdf_to_images(pdf_data):
    """Convert PDF bytes to images for preview.
    
    Args:
        pdf_data: Binary PDF data
        
    Returns:
        List of PIL Image objects, one per page
    """
    if convert_from_bytes is None:
        return None
    
    try:
        images = convert_from_bytes(pdf_data, dpi=150)
        return images
    except Exception as exc:
        st.warning(f"Could not generate preview: {exc}")
        return None


def init_state():
    if 'forms' not in st.session_state:
        st.session_state.forms = {}
    if 'builder_components' not in st.session_state:
        st.session_state.builder_components = []
    if 'builder_form_name' not in st.session_state:
        st.session_state.builder_form_name = ''

    if 'temp_form_counter' not in st.session_state:
        st.session_state.temp_form_counter = 1

    if 'generated_pdf_data' not in st.session_state:
        st.session_state.generated_pdf_data = None
    if 'generated_pdf_name' not in st.session_state:
        st.session_state.generated_pdf_name = 'form.pdf'

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

    allowed_types = {'Text', 'Text Input', 'Textarea', 'Checkbox', 'Image Upload', 'Camera Input'}
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

TYPE_ICONS = {
    'Text': '📝',
    'Text Input': '✏️',
    'Textarea': '📄',
    'Checkbox': '☑️',
    'Image Upload': '🖼️',
    'Camera Input': '📷',
}

@st.dialog('📋 PDF Preview', width='large')
def show_pdf_preview_modal():
    pdf_name = st.session_state.get('generated_pdf_name', 'form')
    pdf_data = st.session_state.get('generated_pdf_data')
    if not pdf_data:
        st.warning('No PDF generated yet.')
        return

    preview_images = pdf_to_images(pdf_data)
    if preview_images:
        st.caption(f'{len(preview_images)} page(s)')
        if len(preview_images) == 1:
            st.image(preview_images[0], use_column_width=True, caption='Page 1')
        else:
            page_tabs = st.tabs([f'Page {i + 1}' for i in range(len(preview_images))])
            for idx, tab in enumerate(page_tabs):
                with tab:
                    st.image(preview_images[idx], use_column_width=True, caption=f'Page {idx + 1}')
    else:
        st.info('PDF image preview not available — install poppler-utils to enable it.')
        st.code('sudo apt-get install poppler-utils && pip install pdf2image', language='bash')

    st.markdown('---')
    st.download_button(
        '⬇️ Download PDF',
        data=pdf_data,
        file_name=f'{pdf_name}_basic.pdf',
        mime='application/pdf',
        use_container_width=True,
    )


# Responsive layout: tabs on narrow, 2-col on medium, 3-col on wide
_screen_width = (
    streamlit_js_eval(js_expressions='window.innerWidth', key='screen_width_checklist')
    if streamlit_js_eval
    else None
)

if _screen_width is None or _screen_width < 640:
    forms_tab, builder_tab, render_tab = st.tabs(['📂 My Forms', '📝 Form Builder', '📋 Render & Export'])
else:
    _col1, _col2 = st.columns([1, 2])
    forms_tab = _col1
    with _col2:
        builder_tab, render_tab = st.tabs(['📝 Form Builder', '📋 Render & Export'])

# ── Tab 1: My Forms ───────────────────────────────────────────────────────────
with forms_tab:
    st.subheader('📂 My Forms')

    form_names = list(st.session_state.forms.keys())

    # Import form JSON (first)
    st.markdown('**📤 Import Form**')
    import_file = st.file_uploader('Import form JSON', type=['json'], key='import_form_json')
    import_target_name = st.text_input('Imported form name override (optional)', key='import_form_name_override')
    if st.button('📤 Import Form', use_container_width=True):
        if import_file is None:
            st.error('Choose a JSON file to import.')
        else:
            try:
                imported_name, imported_components = parse_imported_form(import_file.getvalue())
                target_name = import_target_name.strip() or imported_name or f"imported_form_{st.session_state.temp_form_counter}"
                if not imported_name and not import_target_name.strip():
                    st.session_state.temp_form_counter += 1
                st.session_state.forms[target_name] = {'components': imported_components}
                load_builder_from_form(target_name)
                st.session_state.pending_save_form_name = target_name
                st.success(f'✅ Imported form: "{target_name}".')
                trigger_rerun()
            except Exception as exc:
                st.error(f'Import failed: {exc}')

    st.markdown('---')

    # Form list with stats
    if form_names:
        st.markdown(f'**{len(form_names)} form(s) in session:**')
        for name in form_names:
            comps = st.session_state.forms[name].get('components', [])
            count = len(comps)
            active_badge = ' ← **active**' if name == st.session_state.builder_form_name else ''
            st.markdown(f'- 📋 **{name}** — {count} component(s){active_badge}')
    else:
        st.info('No forms yet. Create one below.')

    st.markdown('---')

    # Create new form
    st.markdown('**➕ Create New Form**')
    new_name = st.text_input('Form name', key='new_form_name', placeholder='e.g. Site Inspection Checklist')
    if st.button('Create Form', use_container_width=True):
        if not new_name.strip():
            st.error('Please enter a form name.')
        elif new_name.strip() in st.session_state.forms:
            st.error(f'A form named "{new_name.strip()}" already exists.')
        else:
            name_to_create = new_name.strip()
            st.session_state.forms[name_to_create] = {'components': []}
            st.session_state.builder_form_name = name_to_create
            st.session_state.builder_components = []
            st.session_state.pending_save_form_name = name_to_create
            st.success(f'✅ Created "{name_to_create}". Go to 📝 Form Builder to add components.')
            trigger_rerun()

    st.markdown('---')

    if form_names:
        # Load / switch active form
        st.markdown('**📂 Load Form into Builder**')
        selected_form = st.selectbox(
            'Select form',
            form_names,
            index=form_names.index(st.session_state.builder_form_name) if st.session_state.builder_form_name in form_names else 0,
            key='forms_tab_select',
        )
        if st.button('Load Form', use_container_width=True):
            load_builder_from_form(selected_form)
            st.session_state.pending_save_form_name = selected_form
            st.success(f'✅ Loaded "{selected_form}" into the builder.')
            trigger_rerun()

        st.markdown('---')

        # Duplicate form
        st.markdown('**📋 Duplicate Form**')
        dup_source = st.selectbox('Form to duplicate', form_names, key='dup_source_select')
        dup_name = st.text_input('Name for the duplicate', key='dup_form_name_input', placeholder='e.g. My Form (copy)')
        if st.button('Duplicate Form', use_container_width=True):
            if not dup_name.strip():
                st.error('Enter a name for the duplicate.')
            elif dup_name.strip() in st.session_state.forms:
                st.error(f'A form named "{dup_name.strip()}" already exists.')
            else:
                src_comps = st.session_state.forms[dup_source].get('components', [])
                st.session_state.forms[dup_name.strip()] = {'components': list(src_comps)}
                st.success(f'✅ Duplicated "{dup_source}" → "{dup_name.strip()}".')
                trigger_rerun()

        st.markdown('---')

        # Delete form
        st.markdown('**🗑️ Delete Form**')
        del_form = st.selectbox('Form to delete', form_names, key='del_form_select')
        if st.button('Delete Form', use_container_width=True, type='primary'):
            if len(form_names) == 1:
                st.error('Cannot delete the only form. Create another one first.')
            else:
                st.session_state.forms.pop(del_form, None)
                if del_form == st.session_state.builder_form_name:
                    remaining = list(st.session_state.forms.keys())
                    load_builder_from_form(remaining[0])
                    st.session_state.pending_save_form_name = remaining[0]
                st.success(f'🗑️ Deleted "{del_form}".')
                trigger_rerun()

    st.markdown('---')

    # Export
    st.markdown('**⬇️ Export Form**')
    export_form_name = st.session_state.save_form_name.strip() or st.session_state.builder_form_name
    export_payload = {
        'name': export_form_name,
        'components': list(st.session_state.builder_components),
    }
    st.download_button(
        '⬇️ Export Active Form as JSON',
        data=json.dumps(export_payload, indent=2).encode('utf-8'),
        file_name=f'{export_form_name}.json',
        mime='application/json',
        use_container_width=True,
    )

# ── Tab 2: Form Builder ───────────────────────────────────────────────────────
with builder_tab:
    active_form_name = st.session_state.builder_form_name
    comp_count = len(st.session_state.builder_components)

    st.subheader('📝 Form Builder')
    st.info(f'Active form: **{active_form_name}** — {comp_count} component(s). Manage or switch forms in the 📂 My Forms tab.')

    save_form_name = st.text_input('Form name to save', key='save_form_name')

    st.markdown('---')
    st.markdown('**➕ Add Component**')
    component_type = st.selectbox(
        'Component type',
        ['Text', 'Text Input', 'Textarea', 'Checkbox', 'Image Upload', 'Camera Input'],
        format_func=lambda t: f'{TYPE_ICONS.get(t, "")} {t}',
    )
    component_label = st.text_input('Component label', key='builder_component_label', placeholder='e.g. Inspector Name')
    checkbox_default = st.checkbox('Default checked', key='builder_checkbox_default') if component_type == 'Checkbox' else False

    add_col, save_col = st.columns(2)
    with add_col:
        if st.button('➕ Add Component', use_container_width=True):
            if not component_label.strip():
                st.error('Component label is required.')
            else:
                entry = {'type': component_type, 'label': component_label.strip()}
                if component_type == 'Checkbox':
                    entry['default'] = checkbox_default
                st.session_state.builder_components.append(entry)
                st.success(f'✅ Added {TYPE_ICONS.get(component_type, "")} {component_type}: {component_label.strip()}')
    with save_col:
        if st.button('💾 Save Form', use_container_width=True):
            target_name = save_form_name.strip()
            if not target_name:
                st.error('Enter a form name to save.')
            else:
                previous_name = active_form_name
                st.session_state.forms[target_name] = {'components': list(st.session_state.builder_components)}
                if previous_name != target_name and previous_name.startswith('temp_form_'):
                    st.session_state.forms.pop(previous_name, None)
                st.session_state.builder_form_name = target_name
                st.success(f'✅ Saved form: "{target_name}".')
                trigger_rerun()

    if st.session_state.builder_components:
        st.markdown('---')
        st.markdown(f'**Components ({comp_count})**')

        for index, component in enumerate(st.session_state.builder_components, start=1):
            icon = TYPE_ICONS.get(component['type'], '•')
            if component['type'] == 'Checkbox':
                st.write(f"{index}. {icon} **{component['label']}** `{component['type']}` (default={component.get('default', False)})")
            else:
                st.write(f"{index}. {icon} **{component['label']}** `{component['type']}`")

        st.markdown('---')
        st.markdown('**Edit / Delete / Reorder**')

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
            if st.button('✏️ Update', use_container_width=True):
                if not edit_label.strip():
                    st.error('Label cannot be empty.')
                else:
                    st.session_state.builder_components[selected_idx]['label'] = edit_label.strip()
                    if selected_component.get('type') == 'Checkbox':
                        st.session_state.builder_components[selected_idx]['default'] = edit_default
                    st.success('✅ Updated.')
        with action_cols[1]:
            if st.button('🗑️ Delete', use_container_width=True):
                st.session_state.builder_components.pop(selected_idx)
                st.success('🗑️ Deleted.')
        with action_cols[2]:
            if st.button('⬆️ Up', use_container_width=True) and selected_idx > 0:
                comps = st.session_state.builder_components
                comps[selected_idx - 1], comps[selected_idx] = comps[selected_idx], comps[selected_idx - 1]
                st.success('⬆️ Moved up.')
        with action_cols[3]:
            if st.button('⬇️ Down', use_container_width=True) and selected_idx < len(st.session_state.builder_components) - 1:
                comps = st.session_state.builder_components
                comps[selected_idx + 1], comps[selected_idx] = comps[selected_idx], comps[selected_idx + 1]
                st.success('⬇️ Moved down.')

# ── Tab 3: Render & Export ────────────────────────────────────────────────────
with render_tab:
    active_form_name = st.session_state.builder_form_name
    comp_count = len(st.session_state.builder_components)

    st.subheader('📋 Render & Export')

    if not st.session_state.builder_components:
        st.info('Add at least one component in the 📝 Form Builder tab to fill and export.')
    else:
        st.markdown(f'### {active_form_name}')
        st.caption(f'{comp_count} field(s) — fill in the form below, then generate a PDF preview.')
        st.markdown('---')

        live_values = render_components(st.session_state.builder_components, 'live_render')

        st.markdown('---')

        export_name = st.session_state.save_form_name.strip() or active_form_name

        # Validation: warn about empty text fields
        empty_fields = [
            comp.get('label', '')
            for comp in st.session_state.builder_components
            if comp.get('type') in ('Text Input', 'Textarea')
            and not (live_values.get(comp.get('label', ''), '') or '').strip()
        ]
        if empty_fields:
            st.warning(f'⚠️ {len(empty_fields)} field(s) are empty: {", ".join(empty_fields)}. You can still generate the PDF.')

        col1, col2 = st.columns(2)
        with col1:
            if st.button('📄 Generate & Preview PDF', use_container_width=True):
                pdf_data = build_pdf(export_name, st.session_state.builder_components, live_values)
                st.session_state.generated_pdf_data = pdf_data
                st.session_state.generated_pdf_name = export_name
                show_pdf_preview_modal()
        with col2:
            if st.session_state.generated_pdf_data:
                if st.button('👁️ View Last Preview', use_container_width=True):
                    show_pdf_preview_modal()
