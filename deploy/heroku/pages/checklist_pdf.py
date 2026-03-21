import os
import tempfile
import json
import base64
import inspect
import math
from datetime import date, datetime, timezone
from email.message import EmailMessage
from io import BytesIO
from urllib.parse import quote, urlparse, unquote

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

try:
    from pymongo import ASCENDING, MongoClient
except ImportError:
    ASCENDING = None
    MongoClient = None

try:
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials as GoogleOAuthCredentials
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build as build_google_service
except ImportError:
    service_account = None
    GoogleOAuthCredentials = None
    GoogleAuthRequest = None
    InstalledAppFlow = None
    build_google_service = None

try:
    from pyhanko.sign import signers
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
except ImportError:
    signers = None
    IncrementalPdfFileWriter = None

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
except ImportError:
    x509 = None
    hashes = None
    serialization = None
    rsa = None
    pkcs12 = None
    NameOID = None

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


COMPONENT_TYPES = (
    'Text',
    'Text Input',
    'Textarea',
    'Date Picker',
    'Dropdown',
    'Checkbox',
    'Image Upload',
    'Camera Input',
    'Signature',
    'Table',
)

TABLE_COLUMN_TYPES = (
    'Text Input',
    'Textarea',
    'Date Picker',
    'Dropdown',
    'Checkbox',
    'Image Upload',
    'Camera Input',
    'Signature',
)


def _coerce_table_rows(value):
    try:
        row_count = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(25, row_count))


def _clean_dropdown_options(options):
    if not isinstance(options, list):
        options = []
    cleaned = [str(opt).strip() for opt in options if str(opt).strip()]
    return cleaned


def _normalize_table_columns(columns):
    if not isinstance(columns, list):
        columns = []

    normalized = []
    for idx, column in enumerate(columns):
        if not isinstance(column, dict):
            continue

        name = column.get('name', f'Column {idx + 1}')
        col_type = column.get('type', 'Text Input')

        if not isinstance(name, str) or not name.strip():
            continue
        if col_type not in TABLE_COLUMN_TYPES:
            col_type = 'Text Input'

        cleaned_column = {
            'name': name.strip(),
            'type': col_type,
        }

        if col_type == 'Dropdown':
            options = _clean_dropdown_options(column.get('options', []))
            cleaned_column['options'] = options or ['Option 1']

        normalized.append(cleaned_column)

    return normalized or [{'name': 'Column 1', 'type': 'Text Input'}]


def _parse_date_value(value):
    if value in (None, ''):
        return None

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).date()
    except Exception:
        pass

    try:
        return datetime.strptime(text, '%Y-%m-%d').date()
    except Exception:
        return None


def _normalize_date_default(value):
    parsed = _parse_date_value(value)
    return parsed.isoformat() if parsed is not None else ''


def _normalize_table_default_rows(default_rows, columns):
    if not isinstance(default_rows, list):
        return []

    normalized_rows = []
    for row in default_rows[:25]:
        if not isinstance(row, dict):
            continue

        clean_row = {}
        for column in columns:
            col_name = column.get('name', 'Column')
            col_type = column.get('type', 'Text Input')
            cell_value = row.get(col_name)

            if col_type == 'Checkbox':
                clean_row[col_name] = bool(cell_value)
            elif col_type == 'Date Picker':
                clean_row[col_name] = _normalize_date_default(cell_value)
            elif col_type == 'Dropdown':
                options = _clean_dropdown_options(column.get('options', [])) or ['Option 1']
                clean_row[col_name] = cell_value if cell_value in options else options[0]
            elif col_type in ('Image Upload', 'Camera Input'):
                clean_row[col_name] = None
            else:
                clean_row[col_name] = str(cell_value or '')

        normalized_rows.append(clean_row)

    return normalized_rows


def _normalize_component_entry(component, form_columns):
    if not isinstance(component, dict):
        return None

    comp_type = component.get('type')
    label = component.get('label')
    if comp_type not in COMPONENT_TYPES:
        return None
    if not isinstance(label, str) or not label.strip():
        return None

    normalized = {
        'type': comp_type,
        'label': label.strip(),
        'span': _coerce_span(component.get('span'), form_columns, comp_type),
    }

    if comp_type == 'Checkbox':
        normalized['default'] = bool(component.get('default', False))
    elif comp_type in ('Text Input', 'Textarea', 'Signature'):
        normalized['default_value'] = str(component.get('default_value', '') or '')
    elif comp_type == 'Date Picker':
        normalized['default_value'] = _normalize_date_default(component.get('default_value', ''))
    elif comp_type == 'Dropdown':
        options = _clean_dropdown_options(component.get('options', []))
        normalized['options'] = options or ['Option 1']
        dropdown_default = component.get('default_value', '')
        normalized['default_value'] = dropdown_default if dropdown_default in normalized['options'] else normalized['options'][0]
    elif comp_type == 'Table':
        normalized['columns'] = _normalize_table_columns(component.get('columns', []))
        normalized['initial_rows'] = _coerce_table_rows(component.get('initial_rows', 1))
        normalized['default_rows'] = _normalize_table_default_rows(component.get('default_rows', []), normalized['columns'])

    return normalized


def _default_span_for_type(comp_type, total_columns):
    if comp_type in ('Textarea', 'Image Upload', 'Camera Input', 'Text', 'Signature', 'Table'):
        return total_columns
    return 1


def _coerce_layout_columns(value):
    try:
        columns = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(4, columns))


def _coerce_span(value, total_columns, comp_type):
    try:
        span = int(value)
    except (TypeError, ValueError):
        span = _default_span_for_type(comp_type, total_columns)
    return max(1, min(total_columns, span))


def _init_widget_state(widget_key, value):
    if widget_key not in st.session_state:
        st.session_state[widget_key] = value


def _table_default_cell_value(column):
    col_type = column.get('type', 'Text Input')
    if col_type == 'Checkbox':
        return False
    if col_type == 'Date Picker':
        return None
    return ''


def _build_default_table_row(columns):
    return {
        column.get('name', f'Column {idx + 1}'): _table_default_cell_value(column)
        for idx, column in enumerate(columns)
    }


def _sanitize_table_editor_value(value, col_type, options=None):
    try:
        if math.isnan(value):
            value = None
    except (TypeError, AttributeError):
        pass

    if col_type == 'Checkbox':
        return bool(value)

    if col_type == 'Date Picker':
        return value if value not in ('', None) else None

    if col_type == 'Dropdown':
        cleaned_options = _clean_dropdown_options(options or []) or ['Option 1']
        if value in cleaned_options:
            return value
        return cleaned_options[0]

    return str(value or '')


def _get_data_editor_callable():
    if hasattr(st, 'data_editor'):
        return st.data_editor
    if hasattr(st, 'experimental_data_editor'):
        return st.experimental_data_editor
    return None


def _build_table_editor_column_config(columns):
    if not hasattr(st, 'column_config'):
        return {}

    config = {}
    for column in columns:
        col_name = column.get('name', 'Column')
        col_type = column.get('type', 'Text Input')

        if col_type == 'Checkbox':
            config[col_name] = st.column_config.CheckboxColumn(col_name)
        elif col_type == 'Date Picker':
            config[col_name] = st.column_config.DateColumn(col_name, format='YYYY-MM-DD')
        elif col_type == 'Dropdown':
            options = _clean_dropdown_options(column.get('options', [])) or ['Option 1']
            config[col_name] = st.column_config.SelectboxColumn(col_name, options=options)
        else:
            config[col_name] = st.column_config.TextColumn(col_name)

    return config


def _extract_editor_rows(edited_value):
    if edited_value is None:
        return []

    if isinstance(edited_value, list):
        return [row for row in edited_value if isinstance(row, dict)]

    if isinstance(edited_value, dict):
        data_rows = edited_value.get('data')
        if isinstance(data_rows, list):
            return [row for row in data_rows if isinstance(row, dict)]
        return []

    if hasattr(edited_value, 'to_dict'):
        try:
            return edited_value.to_dict(orient='records')
        except Exception:
            return []

    return []


def _render_table_media_fields(columns, rows_data, key_prefix, idx):
    media_columns = [
        column
        for column in columns
        if column.get('type') in ('Image Upload', 'Camera Input')
    ]
    if not media_columns:
        return

    with st.expander('Row media fields', expanded=False):
        for row_idx, row_entry in enumerate(rows_data):
            st.caption(f'Row {row_idx + 1}')
            widget_cols = st.columns(max(1, len(media_columns)))
            for media_idx, column in enumerate(media_columns):
                col_name = column.get('name', f'Column {media_idx + 1}')
                col_type = column.get('type', 'Image Upload')
                widget_key = f'{key_prefix}_table_media_{idx}_{row_idx}_{media_idx}'
                with widget_cols[media_idx]:
                    if col_type == 'Image Upload':
                        row_entry[col_name] = st.file_uploader(
                            col_name,
                            type=['png', 'jpg', 'jpeg'],
                            key=widget_key,
                        )
                    else:
                        row_entry[col_name] = st.camera_input(col_name, key=widget_key)


def _render_table_component(component, key_prefix, idx, values):
    label = component.get('label', f'Table {idx + 1}')
    columns = _normalize_table_columns(component.get('columns', []))
    initial_rows = _coerce_table_rows(component.get('initial_rows', 1))

    st.markdown(f'**{label}**')
    rows_state_key = f'{key_prefix}_table_rows_data_{idx}'
    data_editor_key = f'{key_prefix}_table_editor_{idx}'

    if rows_state_key not in st.session_state:
        default_rows = _normalize_table_default_rows(component.get('default_rows', []), columns)
        if default_rows:
            st.session_state[rows_state_key] = default_rows
        else:
            seed_row = _build_default_table_row(columns)
            st.session_state[rows_state_key] = [dict(seed_row) for _ in range(initial_rows)]

    existing_rows = st.session_state.get(rows_state_key, [])
    if not isinstance(existing_rows, list):
        existing_rows = []

    editor_columns = [
        column
        for column in columns
        if column.get('type') not in ('Image Upload', 'Camera Input')
    ]

    editor_rows = []
    for row_entry in existing_rows:
        if not isinstance(row_entry, dict):
            row_entry = {}
        editor_row = {}
        for column in editor_columns:
            col_name = column.get('name', 'Column')
            editor_row[col_name] = row_entry.get(col_name, _table_default_cell_value(column))
        editor_rows.append(editor_row)

    if not editor_rows:
        editor_rows = [_build_default_table_row(editor_columns)] if editor_columns else [{}]

    data_editor_fn = _get_data_editor_callable()
    if data_editor_fn is None:
        st.warning('Table editor is unavailable in this Streamlit version.')
        values[label] = existing_rows
        return

    if editor_columns:
        edited = data_editor_fn(
            editor_rows,
            key=data_editor_key,
            num_rows='dynamic',
            use_container_width=True,
            hide_index=True,
            column_config=_build_table_editor_column_config(editor_columns),
        )

        edited_rows = _extract_editor_rows(edited)
        if len(edited_rows) > 25:
            st.warning('Maximum 25 rows are supported. Extra rows were ignored.')
            edited_rows = edited_rows[:25]

        if not edited_rows:
            edited_rows = [_build_default_table_row(editor_columns)]
    else:
        row_count_key = f'{key_prefix}_table_media_only_rows_{idx}'
        if row_count_key not in st.session_state:
            st.session_state[row_count_key] = max(1, min(25, len(existing_rows) or initial_rows))
        st.session_state[row_count_key] = st.number_input(
            'Rows',
            min_value=1,
            max_value=25,
            value=int(st.session_state.get(row_count_key, 1)),
            step=1,
            key=f'{row_count_key}_input',
        )
        edited_rows = [{} for _ in range(int(st.session_state[row_count_key]))]

    merged_rows = []
    for row_idx, editor_row in enumerate(edited_rows):
        base_row = {}
        previous_row = existing_rows[row_idx] if row_idx < len(existing_rows) and isinstance(existing_rows[row_idx], dict) else {}

        for column in columns:
            col_name = column.get('name', 'Column')
            col_type = column.get('type', 'Text Input')

            if col_type in ('Image Upload', 'Camera Input'):
                base_row[col_name] = previous_row.get(col_name)
            else:
                base_row[col_name] = _sanitize_table_editor_value(
                    editor_row.get(col_name),
                    col_type,
                    column.get('options', []),
                )

        merged_rows.append(base_row)

    _render_table_media_fields(columns, merged_rows, key_prefix, idx)
    st.caption(f'{len(merged_rows)} row(s)')

    st.session_state[rows_state_key] = merged_rows
    values[label] = merged_rows


def _render_one_component(component, key_prefix, idx, values):
    comp_type = component.get('type')
    label = component.get('label', f'Field {idx + 1}')
    if comp_type == 'Text':
        st.markdown(f'**{label}**')
    elif comp_type == 'Text Input':
        widget_key = f'{key_prefix}_text_{idx}'
        _init_widget_state(widget_key, str(component.get('default_value', '') or ''))
        values[label] = st.text_input(label, key=widget_key)
    elif comp_type == 'Textarea':
        widget_key = f'{key_prefix}_textarea_{idx}'
        _init_widget_state(widget_key, str(component.get('default_value', '') or ''))
        values[label] = st.text_area(label, key=widget_key)
    elif comp_type == 'Date Picker':
        widget_key = f'{key_prefix}_date_{idx}'
        parsed_date = _parse_date_value(component.get('default_value', ''))
        if parsed_date is not None:
            _init_widget_state(widget_key, parsed_date)
        values[label] = st.date_input(label, key=widget_key)
    elif comp_type == 'Dropdown':
        options = component.get('options', [])
        if not isinstance(options, list):
            options = []
        cleaned_options = [str(opt).strip() for opt in options if str(opt).strip()]
        if not cleaned_options:
            cleaned_options = ['Option 1']
        widget_key = f'{key_prefix}_dropdown_{idx}'
        default_option = component.get('default_value', cleaned_options[0])
        if default_option not in cleaned_options:
            default_option = cleaned_options[0]
        _init_widget_state(widget_key, default_option)
        values[label] = st.selectbox(label, cleaned_options, key=widget_key)
    elif comp_type == 'Checkbox':
        values[label] = st.checkbox(
            label,
            value=component.get('default', False),
            key=f'{key_prefix}_checkbox_{idx}',
        )
    elif comp_type == 'Signature':
        widget_key = f'{key_prefix}_signature_{idx}'
        _init_widget_state(widget_key, str(component.get('default_value', '') or ''))
        values[label] = st.text_input(
            label,
            key=widget_key,
            placeholder='Type full name as signature',
        )
    elif comp_type == 'Image Upload':
        values[label] = st.file_uploader(
            label,
            type=['png', 'jpg', 'jpeg'],
            accept_multiple_files=True,
            key=f'{key_prefix}_image_{idx}',
        )
    elif comp_type == 'Camera Input':
        values[label] = st.camera_input(
            label,
            key=f'{key_prefix}_camera_{idx}',
        )
    elif comp_type == 'Table':
        _render_table_component(component, key_prefix, idx, values)


def render_components(components, key_prefix, form_columns=1):
    values = {}
    total_columns = _coerce_layout_columns(form_columns)

    # Keep mobile simple and readable.
    if _screen_width is not None and _screen_width < 768:
        total_columns = 1

    if total_columns == 1:
        for idx, component in enumerate(components):
            _render_one_component(component, key_prefix, idx, values)
        return values

    rows = []
    current_row = []
    used = 0
    for idx, component in enumerate(components):
        comp_type = component.get('type')
        span = _coerce_span(component.get('span'), total_columns, comp_type)

        if used + span > total_columns and current_row:
            rows.append(current_row)
            current_row = []
            used = 0

        current_row.append((idx, component, span))
        used += span

        if used >= total_columns:
            rows.append(current_row)
            current_row = []
            used = 0

    if current_row:
        rows.append(current_row)

    for row in rows:
        widths = [item[2] for item in row]
        spare = total_columns - sum(widths)
        if spare > 0:
            widths += [1] * spare

        cols = st.columns(widths)
        for col_idx, item in enumerate(row):
            idx, component, _span = item
            with cols[col_idx]:
                _render_one_component(component, key_prefix, idx, values)

    return values


def build_pdf(form_name, components, values, form_columns=1):
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = os.path.join(tmp_dir, 'checklist_output.pdf')
        pdf_canvas = canvas.Canvas(pdf_path, pagesize=letter)
        page_width, page_height = letter

        left_margin = 50
        right_margin = 50
        body_max_w = page_width - left_margin - right_margin
        col_gap = 10
        line_h = 15
        top_margin = 50
        bottom_margin = 50

        total_columns = _coerce_layout_columns(form_columns)

        def _build_rows():
            rows = []
            current_row = []
            used = 0
            for component in components:
                comp_type = component.get('type')
                span = _coerce_span(component.get('span'), total_columns, comp_type)

                if used + span > total_columns and current_row:
                    rows.append(current_row)
                    current_row = []
                    used = 0

                current_row.append((component, span, used))
                used += span

                if used >= total_columns:
                    rows.append(current_row)
                    current_row = []
                    used = 0

            if current_row:
                rows.append(current_row)
            return rows

        def _text_block_lines(text, font_name, font_size, max_width):
            return [(line, font_name, font_size) for line in wrap_text(text, font_name, font_size, max_width)]

        def _component_block(component, cell_width):
            comp_type = component.get('type')
            label = component.get('label', '')
            content_width = max(80, cell_width - 8)
            block = {
                'lines': [],
                'images': [],
                'table': None,
            }

            if comp_type == 'Text':
                block['lines'].extend(_text_block_lines(label, 'Helvetica-Bold', 12, content_width))

            elif comp_type == 'Text Input':
                block['lines'].extend(_text_block_lines(f'{label}:', 'Helvetica', 12, content_width))
                value_text = str(values.get(label, '') or '')
                block['lines'].extend(_text_block_lines(value_text, 'Helvetica', 12, content_width))

            elif comp_type == 'Date Picker':
                value_obj = values.get(label)
                value_text = ''
                if value_obj is not None:
                    value_text = value_obj.isoformat() if hasattr(value_obj, 'isoformat') else str(value_obj)
                block['lines'].extend(_text_block_lines(f'{label}: {value_text}', 'Helvetica', 12, content_width))

            elif comp_type == 'Dropdown':
                value_text = str(values.get(label, '') or '')
                block['lines'].extend(_text_block_lines(f'{label}: {value_text}', 'Helvetica', 12, content_width))

            elif comp_type == 'Textarea':
                block['lines'].extend(_text_block_lines(f'{label}:', 'Helvetica', 12, content_width))
                raw_lines = str(values.get(label, '') or '').split('\n')
                for raw_line in raw_lines:
                    block['lines'].extend(_text_block_lines(raw_line, 'Helvetica', 12, content_width))

            elif comp_type == 'Checkbox':
                checked = 'Yes' if values.get(label, False) else 'No'
                block['lines'].extend(_text_block_lines(f'{label}: {checked}', 'Helvetica', 12, content_width))

            elif comp_type == 'Signature':
                value_text = str(values.get(label, '') or '').strip() or '________________________'
                block['lines'].extend(_text_block_lines(f'{label}: {value_text}', 'Helvetica', 12, content_width))

            elif comp_type in ('Image Upload', 'Camera Input'):
                block['lines'].extend(_text_block_lines(f'{label}:', 'Helvetica', 12, content_width))
                uploaded_value = values.get(label)
                images_to_render = []
                if comp_type == 'Image Upload':
                    if isinstance(uploaded_value, list):
                        images_to_render = [item for item in uploaded_value if item is not None]
                    elif uploaded_value is not None:
                        images_to_render = [uploaded_value]
                else:
                    if uploaded_value is not None:
                        images_to_render = [uploaded_value]

                if not images_to_render:
                    block['lines'].extend(_text_block_lines('(no image uploaded)', 'Helvetica', 12, content_width))
                else:
                    for image_idx, uploaded_img in enumerate(images_to_render, start=1):
                        if comp_type == 'Image Upload' and len(images_to_render) > 1:
                            block['lines'].extend(_text_block_lines(f'Image {image_idx}:', 'Helvetica', 11, content_width))
                        try:
                            image = Image.open(uploaded_img)
                            img_width, img_height = image.size
                            if img_width > 0:
                                max_img_w = content_width
                                display_width = min(max_img_w, float(img_width))
                                display_height = display_width * (float(img_height) / float(img_width))
                                display_height = min(display_height, 180.0)
                                block['images'].append({
                                    'image': image,
                                    'width': display_width,
                                    'height': display_height,
                                })
                            else:
                                block['lines'].extend(_text_block_lines('(image has invalid size)', 'Helvetica', 12, content_width))
                        except Exception as exc:
                            block['lines'].extend(_text_block_lines(f'(image error: {exc})', 'Helvetica', 12, content_width))

            elif comp_type == 'Table':
                block['lines'].extend(_text_block_lines(f'{label}:', 'Helvetica', 12, content_width))
                columns = _normalize_table_columns(component.get('columns', []))
                row_values = values.get(label)

                if not isinstance(row_values, list) or not row_values:
                    block['lines'].extend(_text_block_lines('(no rows added)', 'Helvetica', 12, content_width))
                else:
                    table_columns = [column.get('name', 'Column') for column in columns]
                    table_col_count = max(1, len(table_columns))
                    table_width = content_width
                    col_width = table_width / float(table_col_count)
                    table_font_size = 9
                    table_line_h = 11

                    header_cells = [
                        wrap_text(col_name, 'Helvetica-Bold', table_font_size, max(20, col_width - 6))
                        for col_name in table_columns
                    ]
                    header_height = max(1, max(len(lines) for lines in header_cells)) * table_line_h + 4

                    table_rows = []
                    table_row_heights = []

                    for row_data in row_values:
                        if not isinstance(row_data, dict):
                            row_data = {}

                        rendered_row = []
                        max_lines = 1
                        for column in columns:
                            col_name = column.get('name', 'Column')
                            col_type = column.get('type', 'Text Input')
                            cell_value = row_data.get(col_name)

                            if col_type == 'Checkbox':
                                display_text = 'Yes' if bool(cell_value) else 'No'
                            elif col_type == 'Date Picker':
                                if cell_value is None:
                                    display_text = ''
                                else:
                                    display_text = cell_value.isoformat() if hasattr(cell_value, 'isoformat') else str(cell_value)
                            elif col_type in ('Image Upload', 'Camera Input'):
                                if cell_value is None:
                                    display_text = ''
                                else:
                                    display_text = '(image attached)'
                            else:
                                display_text = str(cell_value or '')

                            wrapped = []
                            for raw_line in display_text.split('\n'):
                                wrapped.extend(wrap_text(raw_line, 'Helvetica', table_font_size, max(20, col_width - 6)))
                            if not wrapped:
                                wrapped = ['']

                            max_lines = max(max_lines, len(wrapped))
                            rendered_row.append(wrapped)

                        table_rows.append(rendered_row)
                        table_row_heights.append(max_lines * table_line_h + 4)

                    table_height = header_height + sum(table_row_heights)
                    block['table'] = {
                        'width': table_width,
                        'columns': table_columns,
                        'col_width': col_width,
                        'header_cells': header_cells,
                        'header_height': header_height,
                        'rows': table_rows,
                        'row_heights': table_row_heights,
                        'font_size': table_font_size,
                        'line_height': table_line_h,
                    }

            if not block['lines']:
                block['lines'].append(('', 'Helvetica', 12))

            text_height = len(block['lines']) * line_h
            if block.get('table') is not None:
                text_height += block['table']['header_height'] + sum(block['table']['row_heights']) + 6
            image_height = sum(item['height'] + 6 for item in block['images'])
            block['height'] = text_height + image_height + 6
            return block

        y_pos = page_height - top_margin
        pdf_canvas.setFont('Helvetica-Bold', 16)
        for title_line in wrap_text(f'Checklist Form: {form_name}', 'Helvetica-Bold', 16, body_max_w):
            pdf_canvas.drawCentredString(page_width / 2, y_pos, title_line)
            y_pos -= 22
        y_pos -= 10

        unit_w = (body_max_w - (col_gap * (total_columns - 1))) / float(total_columns)
        rows = _build_rows()

        for row in rows:
            rendered_cells = []
            row_height = line_h
            for component, span, col_start in row:
                cell_x = left_margin + col_start * (unit_w + col_gap)
                cell_w = unit_w * span + col_gap * (span - 1)
                block = _component_block(component, cell_w)
                rendered_cells.append((cell_x, cell_w, block))
                row_height = max(row_height, block['height'])

            if y_pos - row_height < bottom_margin:
                pdf_canvas.showPage()
                y_pos = page_height - top_margin

            for cell_x, _cell_w, block in rendered_cells:
                text_y = y_pos
                for line_text, font_name, font_size in block['lines']:
                    pdf_canvas.setFont(font_name, font_size)
                    pdf_canvas.drawString(cell_x, text_y, line_text)
                    text_y -= line_h

                table_block = block.get('table')
                if table_block is not None:
                    table_top = text_y - 2
                    table_left = cell_x
                    table_width = table_block['width']
                    col_width = table_block['col_width']
                    header_height = table_block['header_height']
                    row_heights = table_block['row_heights']
                    total_table_height = header_height + sum(row_heights)
                    table_bottom = table_top - total_table_height

                    pdf_canvas.setLineWidth(0.6)
                    pdf_canvas.rect(table_left, table_bottom, table_width, total_table_height)

                    for col_idx in range(1, len(table_block['columns'])):
                        x_line = table_left + (col_idx * col_width)
                        pdf_canvas.line(x_line, table_top, x_line, table_bottom)

                    header_bottom = table_top - header_height
                    pdf_canvas.line(table_left, header_bottom, table_left + table_width, header_bottom)

                    running_y = header_bottom
                    for row_height in row_heights[:-1]:
                        running_y -= row_height
                        pdf_canvas.line(table_left, running_y, table_left + table_width, running_y)

                    header_text_y = table_top - table_block['line_height']
                    for col_idx, header_lines in enumerate(table_block['header_cells']):
                        text_x = table_left + (col_idx * col_width) + 3
                        line_y = header_text_y
                        pdf_canvas.setFont('Helvetica-Bold', table_block['font_size'])
                        for header_line in header_lines:
                            pdf_canvas.drawString(text_x, line_y, header_line)
                            line_y -= table_block['line_height']

                    row_top = header_bottom
                    for row_idx, row_cells in enumerate(table_block['rows']):
                        row_height = row_heights[row_idx]
                        for col_idx, cell_lines in enumerate(row_cells):
                            text_x = table_left + (col_idx * col_width) + 3
                            line_y = row_top - table_block['line_height']
                            pdf_canvas.setFont('Helvetica', table_block['font_size'])
                            for cell_line in cell_lines:
                                if line_y < row_top - row_height + 2:
                                    break
                                pdf_canvas.drawString(text_x, line_y, cell_line)
                                line_y -= table_block['line_height']
                        row_top -= row_height

                    text_y = table_bottom - 6

                for image_item in block['images']:
                    pdf_canvas.drawImage(
                        ImageReader(image_item['image']),
                        cell_x,
                        text_y - image_item['height'],
                        width=image_item['width'],
                        height=image_item['height'],
                        preserveAspectRatio=True,
                        mask='auto',
                    )
                    text_y -= image_item['height'] + 6

            y_pos -= row_height + 6

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


PERSISTENCE_PAGE_KEY = 'checklist_pdf'
GMAIL_SEND_SCOPE = ['https://www.googleapis.com/auth/gmail.send']


def _get_setting(name, default=None):
    env_value = os.getenv(name)
    if env_value is not None and str(env_value).strip():
        return env_value

    try:
        secret_value = st.secrets.get(name, default)
        if secret_value is not None and str(secret_value).strip():
            return secret_value
    except Exception:
        pass

    return default


def _database_name_from_uri(mongo_uri):
    try:
        parsed = urlparse(mongo_uri)
        # mongodb+srv://.../<db_name>?... -> path is '/<db_name>'
        candidate = unquote((parsed.path or '').lstrip('/')).strip()
        if candidate:
            return candidate
    except Exception:
        pass
    return ''


@st.cache_resource(show_spinner=False)
def _get_forms_collection(mongo_uri, db_name, collection_name):
    if MongoClient is None:
        return None

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
    client.admin.command('ping')
    collection = client[db_name][collection_name]
    collection.create_index([('username', ASCENDING), ('page', ASCENDING)], unique=True)
    return collection


def get_forms_collection():
    mongo_uri = _get_setting('MONGODB_URI')
    if not mongo_uri:
        return None

    configured_db_name = _get_setting('MONGODB_DB')
    db_name = str(configured_db_name).strip() if configured_db_name is not None else ''
    if not db_name:
        db_name = _database_name_from_uri(mongo_uri) or 'app_data'
    collection_name = str(_get_setting('MONGODB_FORMS_COLLECTION', 'user_forms')).strip() or 'user_forms'

    try:
        return _get_forms_collection(mongo_uri, db_name, collection_name)
    except Exception:
        return None


def get_persistence_status():
    mongo_uri = _get_setting('MONGODB_URI')
    if not mongo_uri:
        return 'session_only', 'Mongo not configured (set MONGODB_URI).'

    if MongoClient is None:
        return 'session_only', 'Mongo driver not installed (add pymongo).'

    collection = get_forms_collection()
    if collection is None:
        return 'session_only', 'Mongo unavailable (connection failed).'

    return 'mongo', 'Mongo connected. Forms persist per logged-in user.'


def get_authenticated_username():
    username = st.session_state.get('username')
    return str(username).strip() if username else ''


def parse_email_list(raw_text):
    emails = []
    invalid = []

    for line in (raw_text or '').splitlines():
        for part in line.replace(';', ',').split(','):
            candidate = part.strip()
            if not candidate:
                continue
            if '@' not in candidate or candidate.startswith('@') or candidate.endswith('@'):
                invalid.append(candidate)
                continue
            local, domain = candidate.rsplit('@', 1)
            if not local or '.' not in domain:
                invalid.append(candidate)
                continue
            emails.append(candidate)

    # Preserve order while removing duplicates
    unique_emails = list(dict.fromkeys(emails))
    return unique_emails, invalid


def normalize_form_data(form_data):
    if not isinstance(form_data, dict):
        form_data = {}

    components = form_data.get('components', [])
    form_columns = form_data.get('form_columns', 1)
    email_recipients_text = form_data.get('email_recipients_text', '')
    email_optional_message = form_data.get('email_optional_message', '')

    if not isinstance(components, list):
        components = []
    form_columns = _coerce_layout_columns(form_columns)
    normalized_components = []
    for item in components:
        normalized_item = _normalize_component_entry(item, form_columns)
        if normalized_item is not None:
            normalized_components.append(normalized_item)

    if not isinstance(email_recipients_text, str):
        email_recipients_text = ''
    if not isinstance(email_optional_message, str):
        email_optional_message = ''

    return {
        'components': normalized_components,
        'form_columns': form_columns,
        'email_recipients_text': email_recipients_text,
        'email_optional_message': email_optional_message,
    }


def normalize_forms_map(forms):
    if not isinstance(forms, dict):
        return {}

    normalized = {}
    for name, form_data in forms.items():
        if not isinstance(name, str) or not name.strip():
            continue
        normalized[name] = normalize_form_data(form_data)
    return normalized


def get_profile_email_defaults():
    recipients = st.session_state.get('profile_email_recipients_text', '')
    message = st.session_state.get('profile_email_optional_message', '')

    if not isinstance(recipients, str):
        recipients = ''
    if not isinstance(message, str):
        message = ''

    return recipients, message


def get_form_email_settings(form_data):
    form_state = normalize_form_data(form_data)
    profile_recipients, profile_message = get_profile_email_defaults()

    recipients = form_state.get('email_recipients_text', '')
    message = form_state.get('email_optional_message', '')

    if not recipients.strip():
        recipients = profile_recipients
    if not message.strip():
        message = profile_message

    return recipients, message


def sync_active_form_state():
    form_name = st.session_state.get('builder_form_name', '')
    if not isinstance(form_name, str) or not form_name.strip():
        return

    forms = normalize_forms_map(st.session_state.get('forms', {}))
    active_form = normalize_form_data(forms.get(form_name, {}))
    active_form['components'] = list(st.session_state.get('builder_components', []))
    active_form['form_columns'] = _coerce_layout_columns(st.session_state.get('builder_layout_columns', 1))
    active_form['email_recipients_text'] = st.session_state.get('email_recipients_text', '')
    active_form['email_optional_message'] = st.session_state.get('email_optional_message', '')
    forms[form_name] = active_form
    st.session_state.forms = forms


def sync_email_settings_to_profile():
    st.session_state.profile_email_recipients_text = st.session_state.get('email_recipients_text', '')
    st.session_state.profile_email_optional_message = st.session_state.get('email_optional_message', '')
    persist_forms_state()


def _load_json_data(raw_value):
    if raw_value is None:
        return None, None
    if isinstance(raw_value, dict):
        return raw_value, None

    raw_text = str(raw_value).strip()
    if not raw_text:
        return None, None

    if raw_text.startswith('{'):
        return json.loads(raw_text), None

    with open(raw_text, 'r', encoding='utf-8') as source_file:
        return json.load(source_file), raw_text


def _load_google_oauth_credentials_info():
    raw = (
        _get_setting('GMAIL_OAUTH_CREDENTIALS_JSON')
        or _get_setting('GOOGLE_OAUTH_CREDENTIALS_JSON')
        or _get_setting('GMAIL_CREDENTIALS_JSON')
        or 'credentials.json'
    )
    try:
        return _load_json_data(raw)
    except Exception:
        return None, None


def _load_google_oauth_token_info():
    raw = (
        _get_setting('GMAIL_OAUTH_TOKEN_JSON')
        or _get_setting('GOOGLE_OAUTH_TOKEN_JSON')
        or _get_setting('GMAIL_TOKEN_JSON')
        or 'gmail_token.json'
    )
    try:
        return _load_json_data(raw)
    except Exception:
        return None, None


def _load_google_service_account_info():
    raw = _get_setting('GMAIL_SERVICE_ACCOUNT_JSON') or _get_setting('GOOGLE_SERVICE_ACCOUNT_JSON')
    try:
        data, _ = _load_json_data(raw)
        return data
    except Exception:
        return None


def _save_oauth_token_if_possible(token_info, token_path):
    if not token_info or not token_path:
        return
    try:
        with open(token_path, 'w', encoding='utf-8') as token_file:
            json.dump(token_info, token_file)
    except Exception:
        return


def _build_gmail_oauth_credentials(credentials_info, token_info, token_path):
    if GoogleOAuthCredentials is None:
        return None

    credentials = None
    if token_info:
        credentials = GoogleOAuthCredentials.from_authorized_user_info(token_info, GMAIL_SEND_SCOPE)

    if credentials and credentials.expired and credentials.refresh_token and GoogleAuthRequest is not None:
        try:
            credentials.refresh(GoogleAuthRequest())
            _save_oauth_token_if_possible(json.loads(credentials.to_json()), token_path)
        except Exception:
            credentials = None

    if credentials and credentials.valid:
        return credentials

    if not credentials_info or InstalledAppFlow is None:
        return None

    flow = InstalledAppFlow.from_client_config(credentials_info, GMAIL_SEND_SCOPE)
    credentials = flow.run_local_server(port=0)
    _save_oauth_token_if_possible(json.loads(credentials.to_json()), token_path)
    return credentials


@st.cache_resource(show_spinner=False)
def _build_gmail_service_oauth(credentials_payload_text, token_payload_text):
    if build_google_service is None:
        return None

    credentials_info = json.loads(credentials_payload_text) if credentials_payload_text else None
    token_info = json.loads(token_payload_text) if token_payload_text else None
    credentials = _build_gmail_oauth_credentials(credentials_info, token_info, None)
    if credentials is None:
        return None

    return build_google_service('gmail', 'v1', credentials=credentials, cache_discovery=False)


@st.cache_resource(show_spinner=False)
def _build_gmail_service(service_account_payload_text, delegated_user):
    if service_account is None or build_google_service is None:
        return None

    service_account_info = json.loads(service_account_payload_text)
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=GMAIL_SEND_SCOPE,
    )
    if delegated_user:
        credentials = credentials.with_subject(delegated_user)

    return build_google_service('gmail', 'v1', credentials=credentials, cache_discovery=False)


def get_gmail_service():
    sender = str(_get_setting('GMAIL_SENDER_EMAIL', '')).strip()

    oauth_credentials_info, _ = _load_google_oauth_credentials_info()
    oauth_token_info, oauth_token_path = _load_google_oauth_token_info()
    if oauth_credentials_info or oauth_token_info:
        credentials = _build_gmail_oauth_credentials(oauth_credentials_info, oauth_token_info, oauth_token_path)
        if credentials is not None and build_google_service is not None:
            service = build_google_service('gmail', 'v1', credentials=credentials, cache_discovery=False)
            return service, sender, 'oauth'

    service_account_info = _load_google_service_account_info()
    if service_account_info:
        delegated_user = str(
            _get_setting('GMAIL_DELEGATED_USER')
            or sender
            or ''
        ).strip()
        if delegated_user:
            payload_text = json.dumps(service_account_info, sort_keys=True)
            service = _build_gmail_service(payload_text, delegated_user)
            if service is not None:
                return service, delegated_user, 'service_account'

    raise ValueError(
        'Gmail auth not configured. Provide OAuth files (credentials.json + gmail_token.json), '
        'or service-account settings (GMAIL_SERVICE_ACCOUNT_JSON + GMAIL_DELEGATED_USER).'
    )


def get_email_delivery_status():
    try:
        _, sender, mode = get_gmail_service()
        mode_label = 'OAuth' if mode == 'oauth' else 'Service Account'
        sender_label = sender or 'default account'
        return 'ready', f'Gmail connected ({mode_label}). Sender: {sender_label}'
    except Exception as exc:
        return 'not_ready', str(exc)


def create_ephemeral_pkcs12():
    if not all([x509, hashes, serialization, rsa, pkcs12, NameOID]):
        raise ValueError('Cryptography dependencies for signing are not available.')

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, 'US'),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'Dynamic Exec Service'),
            x509.NameAttribute(NameOID.COMMON_NAME, 'Checklist PDF Auto Signer'),
        ]
    )

    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now.replace(year=now.year + 1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )

    return pkcs12.serialize_key_and_certificates(
        name=b'checklist-auto-signer',
        key=private_key,
        cert=certificate,
        cas=None,
        encryption_algorithm=serialization.NoEncryption(),
    )


def create_incremental_writer_with_hybrid_support(input_stream):
    if IncrementalPdfFileWriter is None:
        raise ValueError('pyHanko is not installed.')

    parameters = inspect.signature(IncrementalPdfFileWriter).parameters
    kwargs = {}
    if 'strict' in parameters:
        kwargs['strict'] = False
    if 'allow_hybrid_xrefs' in parameters:
        kwargs['allow_hybrid_xrefs'] = True
    if 'reader_kwargs' in parameters:
        kwargs['reader_kwargs'] = {'strict': False, 'allow_hybrid_xrefs': True}

    return IncrementalPdfFileWriter(input_stream, **kwargs)


def load_signer_from_pkcs12(p12_path):
    if signers is None:
        raise ValueError('pyHanko is not installed.')

    load_fn = signers.SimpleSigner.load_pkcs12
    parameters = inspect.signature(load_fn).parameters

    if 'passphrase' in parameters:
        return load_fn(p12_path, passphrase=None)
    if 'pfx_passphrase' in parameters:
        return load_fn(p12_path, pfx_passphrase=None)
    return load_fn(p12_path, None)


def sign_pdf_bytes(pdf_data):
    if not pdf_data:
        raise ValueError('No PDF data to sign.')

    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = os.path.join(tmp_dir, 'input.pdf')
        p12_path = os.path.join(tmp_dir, 'signer.p12')
        signed_path = os.path.join(tmp_dir, 'signed.pdf')

        with open(pdf_path, 'wb') as pdf_file:
            pdf_file.write(pdf_data)
        with open(p12_path, 'wb') as cert_file:
            cert_file.write(create_ephemeral_pkcs12())

        signer = load_signer_from_pkcs12(p12_path)
        if signer is None:
            raise ValueError('Could not initialize signer from generated PKCS#12 bundle.')

        with open(pdf_path, 'rb') as source_pdf, open(signed_path, 'wb') as output_pdf:
            writer = create_incremental_writer_with_hybrid_support(source_pdf)
            signature_meta = signers.PdfSignatureMetadata(field_name='Signature1')
            pdf_signer = signers.PdfSigner(signature_meta=signature_meta, signer=signer)
            pdf_signer.sign_pdf(writer, output=output_pdf)

        with open(signed_path, 'rb') as signed_file:
            return signed_file.read()


def send_signed_pdf_email(recipients, message_text, signed_pdf_data, filename, form_name):
    if not recipients:
        raise ValueError('At least one recipient email is required.')

    gmail_service, sender, _ = get_gmail_service()

    message = EmailMessage()
    message['To'] = ', '.join(recipients)
    if sender:
        message['From'] = sender
    message['Subject'] = f'Signed checklist PDF: {form_name}'
    body = (message_text or '').strip() or 'Please find the signed checklist PDF attached.'
    message.set_content(body)
    message.add_attachment(
        signed_pdf_data,
        maintype='application',
        subtype='pdf',
        filename=filename,
    )

    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
    gmail_service.users().messages().send(userId='me', body={'raw': encoded}).execute()


def _get_query_param_value(query_params, key):
    value = query_params.get(key)
    if isinstance(value, list):
        value = value[0] if value else ''
    if value is None:
        return ''
    return str(value).strip()


def _get_requested_form_name(query_params):
    """
    Read the requested form name from query params.
    Tolerates unencoded '&' in the form value, e.g.
    ?user=admin&form=CCTV T&A Form
    """
    requested_form_name = _get_query_param_value(query_params, 'form')
    if not requested_form_name:
        return ''

    known_keys = {'form', 'user', 'profile', 'tab'}
    dangling_keys = []
    for key in query_params.keys():
        if key in known_keys:
            continue
        raw_value = query_params.get(key)
        if isinstance(raw_value, list):
            raw_value = raw_value[0] if raw_value else ''
        value_text = '' if raw_value is None else str(raw_value).strip()
        if value_text:
            continue
        dangling_keys.append(str(key).strip())

    if dangling_keys and '&' not in requested_form_name:
        requested_form_name = f"{requested_form_name}&{'&'.join(dangling_keys)}"

    return requested_form_name.strip()


def _get_share_page_base_url():
    """Return absolute page URL (scheme + host + path) for sharing."""
    if 'share_page_base_url' not in st.session_state:
        st.session_state.share_page_base_url = ''

    if streamlit_js_eval:
        current_url = streamlit_js_eval(
            js_expressions='window.location.origin + window.location.pathname',
            key='share_page_base_url_probe',
        )
        if isinstance(current_url, str) and current_url.strip():
            st.session_state.share_page_base_url = current_url.strip().rstrip('/')

    if st.session_state.share_page_base_url:
        return st.session_state.share_page_base_url

    configured_base = str(_get_setting('APP_BASE_URL', '') or '').strip()
    if not configured_base:
        return ''

    parsed = urlparse(configured_base)
    if not parsed.scheme or not parsed.netloc:
        return ''

    configured_base = configured_base.rstrip('/')
    if parsed.path and parsed.path not in ('', '/'):
        return configured_base
    return f'{configured_base}/checklist_pdf'


def find_form_for_user(username, form_name):
    if not username or not form_name:
        return None

    collection = get_forms_collection()
    if collection is None:
        return None

    try:
        doc = collection.find_one(
            {'username': username, 'page': PERSISTENCE_PAGE_KEY},
            {'forms': 1},
        )
    except Exception:
        return None

    if not isinstance(doc, dict):
        return None

    forms = normalize_forms_map(doc.get('forms', {}))
    form_data = forms.get(form_name)
    if not isinstance(form_data, dict):
        return None

    return normalize_form_data(form_data)


def _find_existing_shared_copy_name(form_name, source_username, forms):
    shared_base_name = f'{form_name} (from {source_username})'
    if shared_base_name in forms:
        return shared_base_name

    matches = sorted(
        name for name in forms
        if name.startswith(f'{shared_base_name} (copy ')
    )
    return matches[0] if matches else ''


def _build_shared_copy_name(form_name, source_username, forms):
    shared_base_name = f'{form_name} (from {source_username})'
    if shared_base_name not in forms:
        return shared_base_name

    counter = 1
    while True:
        candidate = f'{shared_base_name} (copy {counter})'
        if candidate not in forms:
            return candidate
        counter += 1


def load_persisted_forms(username):

    if not username:
        return None

    collection = get_forms_collection()
    if collection is None:
        return None

    try:
        doc = collection.find_one({'username': username, 'page': PERSISTENCE_PAGE_KEY})
    except Exception:
        return None

    if not isinstance(doc, dict):
        return None

    forms = normalize_forms_map(doc.get('forms', {}))
    builder_components = doc.get('builder_components', [])
    builder_form_name = doc.get('builder_form_name', '')
    email_recipients_text = doc.get('email_recipients_text', '')
    email_optional_message = doc.get('email_optional_message', '')

    if not isinstance(builder_components, list):
        builder_components = []
    if not isinstance(builder_form_name, str):
        builder_form_name = ''
    if not isinstance(email_recipients_text, str):
        email_recipients_text = ''
    if not isinstance(email_optional_message, str):
        email_optional_message = ''

    return {
        'forms': forms,
        'builder_components': builder_components,
        'builder_form_name': builder_form_name,
        'profile_email_recipients_text': email_recipients_text,
        'profile_email_optional_message': email_optional_message,
    }


def persist_forms_state():
    username = get_authenticated_username()
    if not username:
        return

    collection = get_forms_collection()
    if collection is None:
        return

    sync_active_form_state()

    payload = {
        'username': username,
        'page': PERSISTENCE_PAGE_KEY,
        'forms': st.session_state.get('forms', {}),
        'builder_components': st.session_state.get('builder_components', []),
        'builder_form_name': st.session_state.get('builder_form_name', ''),
        'email_recipients_text': st.session_state.get('profile_email_recipients_text', ''),
        'email_optional_message': st.session_state.get('profile_email_optional_message', ''),
        'updated_at': datetime.now(timezone.utc),
    }

    try:
        collection.update_one(
            {'username': username, 'page': PERSISTENCE_PAGE_KEY},
            {'$set': payload},
            upsert=True,
        )
    except Exception:
        return


def init_state():
    current_user = get_authenticated_username()

    if 'forms_loaded_for_user' not in st.session_state:
        st.session_state.forms_loaded_for_user = None

    if st.session_state.forms_loaded_for_user != current_user:
        persisted = load_persisted_forms(current_user)
        if persisted:
            st.session_state.forms = normalize_forms_map(persisted.get('forms', {}))
            st.session_state.builder_components = persisted.get('builder_components', [])
            st.session_state.builder_form_name = persisted.get('builder_form_name', '')
            st.session_state.profile_email_recipients_text = persisted.get('profile_email_recipients_text', '')
            st.session_state.profile_email_optional_message = persisted.get('profile_email_optional_message', '')

            active_form_name = st.session_state.builder_form_name
            if active_form_name:
                active_form = normalize_form_data(st.session_state.forms.get(active_form_name, {}))
                active_form['components'] = list(st.session_state.builder_components)
                st.session_state.forms[active_form_name] = active_form
                st.session_state.builder_layout_columns = _coerce_layout_columns(active_form.get('form_columns', 1))
                st.session_state.email_recipients_text, st.session_state.email_optional_message = get_form_email_settings(active_form)
            else:
                st.session_state.builder_layout_columns = 1
                st.session_state.email_recipients_text = st.session_state.profile_email_recipients_text
                st.session_state.email_optional_message = st.session_state.profile_email_optional_message
        else:
            st.session_state.forms = {}
            st.session_state.builder_components = []
            st.session_state.builder_form_name = ''
            st.session_state.profile_email_recipients_text = ''
            st.session_state.profile_email_optional_message = ''
            st.session_state.email_recipients_text = ''
            st.session_state.email_optional_message = ''
        st.session_state.forms_loaded_for_user = current_user

    if 'forms' not in st.session_state:
        st.session_state.forms = {}
    if 'builder_components' not in st.session_state:
        st.session_state.builder_components = []
    if 'builder_form_name' not in st.session_state:
        st.session_state.builder_form_name = ''
    if 'builder_layout_columns' not in st.session_state:
        st.session_state.builder_layout_columns = 1
    if 'profile_email_recipients_text' not in st.session_state:
        st.session_state.profile_email_recipients_text = ''
    if 'profile_email_optional_message' not in st.session_state:
        st.session_state.profile_email_optional_message = ''

    if 'temp_form_counter' not in st.session_state:
        st.session_state.temp_form_counter = 1

    if 'generated_pdf_data' not in st.session_state:
        st.session_state.generated_pdf_data = None
    if 'generated_pdf_name' not in st.session_state:
        st.session_state.generated_pdf_name = 'form.pdf'
    if 'email_recipients_text' not in st.session_state:
        st.session_state.email_recipients_text = ''
    if 'email_optional_message' not in st.session_state:
        st.session_state.email_optional_message = ''

    if not st.session_state.builder_form_name:
        temp_name = f"temp_form_{st.session_state.temp_form_counter}"
        st.session_state.temp_form_counter += 1
        st.session_state.forms[temp_name] = normalize_form_data({})
        st.session_state.builder_form_name = temp_name
        st.session_state.builder_layout_columns = 1
        st.session_state.builder_components = []
        st.session_state.email_recipients_text = st.session_state.profile_email_recipients_text
        st.session_state.email_optional_message = st.session_state.profile_email_optional_message
        persist_forms_state()


def load_builder_from_form(form_name):
    form = normalize_form_data(st.session_state.forms.get(form_name, {}))
    if form_name:
        st.session_state.forms[form_name] = form
        st.session_state.builder_components = list(form.get('components', []))
        st.session_state.builder_form_name = form_name
        st.session_state.builder_layout_columns = _coerce_layout_columns(form.get('form_columns', 1))
        st.session_state.email_recipients_text, st.session_state.email_optional_message = get_form_email_settings(form)


def parse_imported_form(file_data):
    payload = json.loads(file_data.decode('utf-8'))
    if not isinstance(payload, dict):
        raise ValueError('Imported JSON must be an object.')

    components = payload.get('components')
    if not isinstance(components, list):
        raise ValueError('Imported JSON must include a components array.')

    allowed_types = set(COMPONENT_TYPES)
    imported_form_columns = _coerce_layout_columns(payload.get('form_columns', 1))
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
        if comp_type in ('Text Input', 'Textarea', 'Signature'):
            entry['default_value'] = str(item.get('default_value', '') or '')
        if comp_type == 'Date Picker':
            raw_default_date = item.get('default_value', '')
            if raw_default_date not in (None, '') and _parse_date_value(raw_default_date) is None:
                raise ValueError(f'Date Picker "{label.strip()}" default_value must be YYYY-MM-DD.')
            entry['default_value'] = _normalize_date_default(raw_default_date)
        if comp_type == 'Dropdown':
            options = item.get('options')
            if not isinstance(options, list):
                raise ValueError(f'Dropdown "{label.strip()}" must include an options array.')
            cleaned_options = [str(opt).strip() for opt in options if str(opt).strip()]
            if not cleaned_options:
                raise ValueError(f'Dropdown "{label.strip()}" must include at least one non-empty option.')
            entry['options'] = cleaned_options
            raw_dropdown_default = item.get('default_value', '')
            if raw_dropdown_default in ('', None):
                entry['default_value'] = cleaned_options[0]
            elif raw_dropdown_default not in cleaned_options:
                raise ValueError(f'Dropdown "{label.strip()}" default_value must match one of the options.')
            else:
                entry['default_value'] = raw_dropdown_default
        if comp_type == 'Table':
            columns = item.get('columns')
            if not isinstance(columns, list):
                raise ValueError(f'Table "{label.strip()}" must include a columns array.')

            normalized_columns = []
            for col_idx, column in enumerate(columns):
                if not isinstance(column, dict):
                    raise ValueError(f'Table "{label.strip()}" column #{col_idx + 1} must be an object.')
                col_name = column.get('name')
                col_type = column.get('type')
                if not isinstance(col_name, str) or not col_name.strip():
                    raise ValueError(f'Table "{label.strip()}" column #{col_idx + 1} must include a non-empty name.')
                if col_type not in TABLE_COLUMN_TYPES:
                    raise ValueError(f'Table "{label.strip()}" column "{col_name}" has unsupported type: {col_type}')

                cleaned_column = {'name': col_name.strip(), 'type': col_type}
                if col_type == 'Dropdown':
                    column_options = column.get('options')
                    if not isinstance(column_options, list):
                        raise ValueError(f'Table "{label.strip()}" dropdown column "{col_name}" must include options array.')
                    cleaned_col_options = [str(opt).strip() for opt in column_options if str(opt).strip()]
                    if not cleaned_col_options:
                        raise ValueError(f'Table "{label.strip()}" dropdown column "{col_name}" must include at least one option.')
                    cleaned_column['options'] = cleaned_col_options

                normalized_columns.append(cleaned_column)

            if not normalized_columns:
                raise ValueError(f'Table "{label.strip()}" must include at least one column.')

            entry['columns'] = normalized_columns
            entry['initial_rows'] = _coerce_table_rows(item.get('initial_rows', 1))
            raw_default_rows = item.get('default_rows', [])
            if raw_default_rows not in (None, []) and not isinstance(raw_default_rows, list):
                raise ValueError(f'Table "{label.strip()}" default_rows must be an array of row objects.')
            entry['default_rows'] = _normalize_table_default_rows(raw_default_rows or [], normalized_columns)
        entry['span'] = _coerce_span(item.get('span'), imported_form_columns, comp_type)
        cleaned.append(entry)

    imported_name = payload.get('name', '')
    if not isinstance(imported_name, str):
        imported_name = ''

    imported_recipients = payload.get('email_recipients_text', '')
    imported_message = payload.get('email_optional_message', '')
    if not isinstance(imported_recipients, str):
        imported_recipients = ''
    if not isinstance(imported_message, str):
        imported_message = ''

    return imported_name.strip(), cleaned, imported_recipients, imported_message, imported_form_columns


init_state()

# ── URL Parameter Handling ────────────────────────────────────────────────────
# Own form: ?form=FormName
# Shared form: ?user=Username&form=FormName
query_params = st.query_params
requested_form_name = _get_requested_form_name(query_params)
requested_source_user = (
    _get_query_param_value(query_params, 'user')
    or _get_query_param_value(query_params, 'profile')
)
current_username = get_authenticated_username()
_url_form_message = ''

if requested_form_name:
    if requested_source_user and requested_source_user != current_username:
        existing_shared_copy_name = _find_existing_shared_copy_name(
            requested_form_name,
            requested_source_user,
            st.session_state.forms,
        )
        if existing_shared_copy_name:
            load_builder_from_form(existing_shared_copy_name)
            st.session_state.url_loaded_form = existing_shared_copy_name
            _url_form_message = (
                f'Loaded shared copy of "{requested_form_name}" from user '
                f'**{requested_source_user}** as **{existing_shared_copy_name}**.'
            )
        else:
            source_form = find_form_for_user(requested_source_user, requested_form_name)
            if source_form is None:
                st.warning(
                    f'Form "{requested_form_name}" was not found in user profile '
                    f'"{requested_source_user}".'
                )
            else:
                copy_name = _build_shared_copy_name(
                    requested_form_name,
                    requested_source_user,
                    st.session_state.forms,
                )
                st.session_state.forms[copy_name] = normalize_form_data(source_form)
                load_builder_from_form(copy_name)
                st.session_state.url_loaded_form = copy_name
                st.session_state.url_form_source = requested_source_user
                persist_forms_state()
                _url_form_message = (
                    f'Copied form "{requested_form_name}" from user '
                    f'**{requested_source_user}** as **{copy_name}**.'
                )
    elif requested_form_name in st.session_state.forms:
        load_builder_from_form(requested_form_name)
        st.session_state.url_loaded_form = requested_form_name
        _url_form_message = f'Loaded form via URL: **{requested_form_name}**.'
    elif requested_source_user == current_username:
        st.warning(
            f'Form "{requested_form_name}" was not found in your profile '
            f'"{current_username}".'
        )
    else:
        st.warning(
            'Form not found in the current profile. To open a shared form copy, '
            'include both `user` and `form` in the URL.'
        )

if _url_form_message:
    st.info(_url_form_message)

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
    'Date Picker': '📅',
    'Dropdown': '🔽',
    'Checkbox': '☑️',
    'Image Upload': '🖼️',
    'Camera Input': '📷',
    'Signature': '✍️',
    'Table': '📊',
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
    st.subheader('✉️ Sign and Email PDF')

    delivery_status, delivery_message = get_email_delivery_status()
    if delivery_status == 'ready':
        st.success(delivery_message)
    else:
        st.warning(f'Email not ready: {delivery_message}')

    recipients_raw = st.session_state.get('email_recipients_text', '')
    optional_message = st.session_state.get('email_optional_message', '')

    recipient_emails, invalid_entries = parse_email_list(recipients_raw)
    can_send = delivery_status == 'ready' and bool(recipient_emails) and not invalid_entries

    button_col1, button_col2, button_col3 = st.columns([1, 1, 1.4])
    with button_col1:
        st.download_button(
            '⬇️ Download PDF',
            data=pdf_data,
            file_name=f'{pdf_name}_basic.pdf',
            mime='application/pdf',
            use_container_width=True,
        )
    with button_col2:
        send_now = st.button(
            '📨 Sign and Email PDF Now',
            use_container_width=True,
            disabled=not can_send,
        )
    with button_col3:
        st.markdown('**Recipients**')
        if recipient_emails:
            st.caption('\n'.join(recipient_emails))
        else:
            st.caption('No valid recipients selected.')

    if invalid_entries:
        st.error(f'Invalid email(s): {", ".join(invalid_entries)}')
    elif not recipients_raw.strip():
        st.info('Add recipient emails in Form Builder before sending.')

    if send_now:
        with st.spinner('Signing and sending email...'):
            try:
                signed_pdf_data = sign_pdf_bytes(pdf_data)
                send_signed_pdf_email(
                    recipients=recipient_emails,
                    message_text=optional_message,
                    signed_pdf_data=signed_pdf_data,
                    filename=f'{pdf_name}_signed.pdf',
                    form_name=pdf_name,
                )
                st.success(f'Sent signed PDF to {len(recipient_emails)} recipient(s).')
            except Exception as exc:
                st.error(f'Could not send signed PDF email: {exc}')


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

    persistence_mode, persistence_message = get_persistence_status()
    if persistence_mode == 'mongo':
        st.success(f'Persistence: {persistence_message}')
    else:
        st.warning(f'Persistence: {persistence_message}')

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
                imported_name, imported_components, imported_recipients, imported_message, imported_form_columns = parse_imported_form(import_file.getvalue())
                target_name = import_target_name.strip() or imported_name or f"imported_form_{st.session_state.temp_form_counter}"
                if not imported_name and not import_target_name.strip():
                    st.session_state.temp_form_counter += 1
                st.session_state.forms[target_name] = normalize_form_data({
                    'components': imported_components,
                    'form_columns': imported_form_columns,
                    'email_recipients_text': imported_recipients,
                    'email_optional_message': imported_message,
                })
                load_builder_from_form(target_name)
                st.session_state.pending_save_form_name = target_name
                persist_forms_state()
                st.success(f'✅ Imported form: "{target_name}".')
                trigger_rerun()
            except Exception as exc:
                st.error(f'Import failed: {exc}')

    st.markdown('---')

    # Share active form via URL
    st.markdown('**🔗 Share Active Form**')
    share_username = get_authenticated_username()
    if st.session_state.builder_form_name and share_username:
        active_form = st.session_state.builder_form_name
        page_base_url = _get_share_page_base_url()
        form_param = (
            f'?user={quote(share_username, safe="")}'
            f'&form={quote(active_form, safe="")}'
        )
        share_url = f'{page_base_url}{form_param}' if page_base_url else form_param
        form_url_widget_key = (
            f'form_url_input_{quote(share_username, safe="")}_{quote(active_form, safe="")}'
        )

        col1, col2 = st.columns([3, 1])
        with col1:
            st.text_input(
                'Share this URL:',
                value=share_url,
                disabled=True,
                key=form_url_widget_key,
            )
        with col2:
            if st.button('📋 Copy', use_container_width=True, key='copy_form_url'):
                if streamlit_js_eval:
                    streamlit_js_eval(
                        js_expressions=f"""
                        navigator.clipboard.writeText({json.dumps(share_url)}).then(
                            () => console.log('URL copied'),
                            (err) => console.error('Failed to copy:', err)
                        )
                        """,
                        key='copy_url_to_clipboard'
                    )
                    st.success('✅ URL copied to clipboard!')
                elif page_base_url:
                    st.error('Clipboard copy is unavailable. Please copy the URL manually from the field.')
                else:
                    st.error('Could not detect full URL in this session. Set APP_BASE_URL to enable full-link fallback.')
    else:
        st.info('Select or create a form to share it.')

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
            st.session_state.forms[name_to_create] = normalize_form_data({})
            st.session_state.builder_form_name = name_to_create
            st.session_state.builder_layout_columns = 1
            st.session_state.builder_components = []
            st.session_state.email_recipients_text = st.session_state.profile_email_recipients_text
            st.session_state.email_optional_message = st.session_state.profile_email_optional_message
            st.session_state.pending_save_form_name = name_to_create
            persist_forms_state()
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
            persist_forms_state()
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
                source_form = normalize_form_data(st.session_state.forms.get(dup_source, {}))
                st.session_state.forms[dup_name.strip()] = normalize_form_data({
                    'components': list(source_form.get('components', [])),
                    'form_columns': source_form.get('form_columns', 1),
                    'email_recipients_text': source_form.get('email_recipients_text', ''),
                    'email_optional_message': source_form.get('email_optional_message', ''),
                })
                persist_forms_state()
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
                persist_forms_state()
                st.success(f'🗑️ Deleted "{del_form}".')
                trigger_rerun()

    st.markdown('---')

    # Export
    st.markdown('**⬇️ Export Form**')
    export_form_name = st.session_state.save_form_name.strip() or st.session_state.builder_form_name
    export_payload = {
        'name': export_form_name,
        'form_columns': _coerce_layout_columns(st.session_state.get('builder_layout_columns', 1)),
        'components': list(st.session_state.builder_components),
        'email_recipients_text': st.session_state.get('email_recipients_text', ''),
        'email_optional_message': st.session_state.get('email_optional_message', ''),
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
    st.markdown('**📐 Layout**')
    st.caption('Desktop layout supports 1 to 4 columns. On mobile, fields stack to one column.')
    st.select_slider(
        'Columns per row',
        options=[1, 2, 3, 4],
        key='builder_layout_columns',
        on_change=persist_forms_state,
    )

    st.markdown('---')
    st.markdown('**✉️ Sign and Email Settings**')
    st.caption('Recipients: newline-delimited list. Message is optional and included in the email body.')

    email_status, email_status_message = get_email_delivery_status()
    if email_status == 'ready':
        st.success(email_status_message)
    else:
        st.warning(f'Email not ready: {email_status_message}')

    st.text_area(
        'Recipient emails (one per line)',
        key='email_recipients_text',
        placeholder='person1@example.com\nperson2@example.com',
        height=120,
        on_change=sync_email_settings_to_profile,
    )
    st.text_area(
        'Optional email message',
        key='email_optional_message',
        placeholder='Please review the attached signed checklist PDF.',
        height=100,
        on_change=sync_email_settings_to_profile,
    )

    st.markdown('---')
    st.markdown('**➕ Add Component**')
    component_type = st.selectbox(
        'Component type',
        list(COMPONENT_TYPES),
        format_func=lambda t: f'{TYPE_ICONS.get(t, "")} {t}',
    )
    selected_layout_columns = _coerce_layout_columns(st.session_state.get('builder_layout_columns', 1))
    suggested_span = _default_span_for_type(component_type, selected_layout_columns)
    if selected_layout_columns == 1:
        component_span = 1
        st.caption('Component width: full row (1 of 1).')
    else:
        component_span = st.slider(
            'Component width (columns)',
            min_value=1,
            max_value=selected_layout_columns,
            value=suggested_span,
            key='builder_component_span',
            help='How many columns this component should span in the current form layout.',
        )
    component_label = st.text_input('Component label', key='builder_component_label', placeholder='e.g. Inspector Name')
    checkbox_default = st.checkbox('Default checked', key='builder_checkbox_default') if component_type == 'Checkbox' else False
    component_default_value_text = ''
    component_default_date_text = ''
    dropdown_options_text = ''
    dropdown_default_value_text = ''
    if component_type == 'Dropdown':
        dropdown_options_text = st.text_area(
            'Dropdown options (one per line)',
            key='builder_dropdown_options',
            placeholder='Routine\nFollow-up\nIncident',
            height=100,
        )
        dropdown_default_value_text = st.text_input(
            'Dropdown default value (optional, must match an option)',
            key='builder_dropdown_default_value',
        )
    if component_type in ('Text Input', 'Textarea', 'Signature'):
        component_default_value_text = st.text_area(
            'Default value (optional)',
            key='builder_component_default_value',
            height=90 if component_type == 'Textarea' else 68,
        )
    if component_type == 'Date Picker':
        component_default_date_text = st.text_input(
            'Default date (optional, YYYY-MM-DD)',
            key='builder_component_default_date',
            placeholder='2026-03-21',
        )
    table_columns = []
    table_initial_rows = 1
    table_default_rows_text = ''
    if component_type == 'Table':
        st.caption('Define table columns and per-column input type.')
        table_col_count = st.number_input(
            'Table column count',
            min_value=1,
            max_value=8,
            value=2,
            key='builder_table_col_count',
        )
        for col_idx in range(int(table_col_count)):
            default_col_name = f'Column {col_idx + 1}'
            col_header = st.text_input(
                f'Column {col_idx + 1} header',
                value=default_col_name,
                key=f'builder_table_col_name_{col_idx}',
            )
            col_type = st.selectbox(
                f'Column {col_idx + 1} type',
                list(TABLE_COLUMN_TYPES),
                key=f'builder_table_col_type_{col_idx}',
            )
            table_column_entry = {
                'name': col_header.strip(),
                'type': col_type,
            }
            if col_type == 'Dropdown':
                options_text = st.text_area(
                    f'Column {col_idx + 1} dropdown options (one per line)',
                    key=f'builder_table_col_options_{col_idx}',
                    height=90,
                )
                table_column_entry['options'] = [line.strip() for line in options_text.splitlines() if line.strip()]
            table_columns.append(table_column_entry)

        table_initial_rows = st.number_input(
            'Initial row count in Render tab',
            min_value=1,
            max_value=25,
            value=1,
            key='builder_table_initial_rows',
        )
        table_default_rows_text = st.text_area(
            'Default rows JSON (optional)',
            key='builder_table_default_rows_json',
            placeholder='[{"Column 1": "Value A", "Column 2": "Value B"}]',
            height=100,
        )

    add_col, save_col = st.columns(2)
    with add_col:
        if st.button('➕ Add Component', use_container_width=True):
            if not component_label.strip():
                st.error('Component label is required.')
            else:
                has_validation_error = False
                entry = {'type': component_type, 'label': component_label.strip()}
                if component_type == 'Checkbox':
                    entry['default'] = checkbox_default
                if component_type in ('Text Input', 'Textarea', 'Signature'):
                    entry['default_value'] = str(component_default_value_text or '')
                if component_type == 'Date Picker':
                    normalized_default_date = _normalize_date_default(component_default_date_text)
                    if component_default_date_text.strip() and not normalized_default_date:
                        st.error('Date default must be YYYY-MM-DD.')
                        has_validation_error = True
                    else:
                        entry['default_value'] = normalized_default_date
                if component_type == 'Dropdown':
                    option_lines = [line.strip() for line in dropdown_options_text.splitlines() if line.strip()]
                    if not option_lines:
                        st.error('Dropdown components require at least one option.')
                        has_validation_error = True
                    else:
                        entry['options'] = option_lines
                        raw_default_option = dropdown_default_value_text.strip()
                        if raw_default_option and raw_default_option not in option_lines:
                            st.error('Dropdown default value must match one of the options.')
                            has_validation_error = True
                        else:
                            entry['default_value'] = raw_default_option or option_lines[0]
                if component_type == 'Table':
                    cleaned_columns = []
                    for column in table_columns:
                        col_name = str(column.get('name', '')).strip()
                        col_type = column.get('type')
                        if not col_name:
                            st.error('Every table column must have a header.')
                            has_validation_error = True
                            cleaned_columns = []
                            break
                        if col_type not in TABLE_COLUMN_TYPES:
                            st.error(f'Unsupported table column type: {col_type}')
                            has_validation_error = True
                            cleaned_columns = []
                            break

                        table_col_entry = {'name': col_name, 'type': col_type}
                        if col_type == 'Dropdown':
                            col_options = [opt.strip() for opt in column.get('options', []) if opt.strip()]
                            if not col_options:
                                st.error(f'Dropdown table column "{col_name}" requires at least one option.')
                                has_validation_error = True
                                cleaned_columns = []
                                break
                            table_col_entry['options'] = col_options
                        cleaned_columns.append(table_col_entry)

                    if cleaned_columns:
                        entry['columns'] = cleaned_columns
                        entry['initial_rows'] = _coerce_table_rows(table_initial_rows)
                        if table_default_rows_text.strip():
                            try:
                                parsed_rows = json.loads(table_default_rows_text)
                            except Exception:
                                st.error('Default rows JSON is invalid.')
                                has_validation_error = True
                                parsed_rows = []
                            entry['default_rows'] = _normalize_table_default_rows(parsed_rows, cleaned_columns)
                        else:
                            entry['default_rows'] = []

                if (
                    not has_validation_error
                    and
                    (component_type != 'Dropdown' or entry.get('options'))
                    and (component_type != 'Table' or entry.get('columns'))
                ):
                    entry['span'] = _coerce_span(component_span, selected_layout_columns, component_type)
                    st.session_state.builder_components.append(entry)
                    persist_forms_state()
                    st.success(f'✅ Added {TYPE_ICONS.get(component_type, "")} {component_type}: {component_label.strip()}')
    with save_col:
        if st.button('💾 Save Form', use_container_width=True):
            target_name = save_form_name.strip()
            if not target_name:
                st.error('Enter a form name to save.')
            else:
                previous_name = active_form_name
                st.session_state.forms[target_name] = normalize_form_data({
                    'components': list(st.session_state.builder_components),
                    'form_columns': _coerce_layout_columns(st.session_state.get('builder_layout_columns', 1)),
                    'email_recipients_text': st.session_state.get('email_recipients_text', ''),
                    'email_optional_message': st.session_state.get('email_optional_message', ''),
                })
                if previous_name != target_name and previous_name.startswith('temp_form_'):
                    st.session_state.forms.pop(previous_name, None)
                st.session_state.builder_form_name = target_name
                persist_forms_state()
                st.success(f'✅ Saved form: "{target_name}".')
                trigger_rerun()

    if st.session_state.builder_components:
        st.markdown('---')
        st.markdown(f'**Components ({comp_count})**')

        for index, component in enumerate(st.session_state.builder_components, start=1):
            icon = TYPE_ICONS.get(component['type'], '•')
            span = _coerce_span(component.get('span'), _coerce_layout_columns(st.session_state.get('builder_layout_columns', 1)), component.get('type'))
            if component['type'] == 'Checkbox':
                st.write(f"{index}. {icon} **{component['label']}** `{component['type']}` (span {span}) (default={component.get('default', False)})")
            else:
                st.write(f"{index}. {icon} **{component['label']}** `{component['type']}` (span {span})")

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
        edit_span = _coerce_span(
            selected_component.get('span'),
            _coerce_layout_columns(st.session_state.get('builder_layout_columns', 1)),
            selected_component.get('type'),
        )
        if selected_component.get('type') == 'Checkbox':
            edit_default = st.checkbox(
                'Checkbox default',
                value=selected_component.get('default', False),
                key=f'edit_component_default_{selected_idx}',
            )
        edit_dropdown_options = []
        edit_default_value_text = ''
        edit_default_date_text = ''
        edit_dropdown_default_text = ''
        if selected_component.get('type') == 'Dropdown':
            existing_options = selected_component.get('options', [])
            if not isinstance(existing_options, list):
                existing_options = []
            edit_options_text = st.text_area(
                'Dropdown options (one per line)',
                value='\n'.join(str(opt) for opt in existing_options),
                key=f'edit_component_options_{selected_idx}',
                height=100,
            )
            edit_dropdown_options = [line.strip() for line in edit_options_text.splitlines() if line.strip()]
            edit_dropdown_default_text = st.text_input(
                'Dropdown default value (optional, must match an option)',
                value=str(selected_component.get('default_value', '') or ''),
                key=f'edit_component_dropdown_default_{selected_idx}',
            )
        if selected_component.get('type') in ('Text Input', 'Textarea', 'Signature'):
            edit_default_value_text = st.text_area(
                'Default value (optional)',
                value=str(selected_component.get('default_value', '') or ''),
                key=f'edit_component_default_value_{selected_idx}',
                height=90 if selected_component.get('type') == 'Textarea' else 68,
            )
        if selected_component.get('type') == 'Date Picker':
            edit_default_date_text = st.text_input(
                'Default date (optional, YYYY-MM-DD)',
                value=str(selected_component.get('default_value', '') or ''),
                key=f'edit_component_default_date_{selected_idx}',
            )
        edit_table_columns = []
        edit_table_initial_rows = _coerce_table_rows(selected_component.get('initial_rows', 1))
        edit_table_default_rows_text = ''
        if selected_component.get('type') == 'Table':
            existing_columns = _normalize_table_columns(selected_component.get('columns', []))
            edit_col_count = st.number_input(
                'Table column count',
                min_value=1,
                max_value=8,
                value=len(existing_columns),
                key=f'edit_table_col_count_{selected_idx}',
            )

            for col_idx in range(int(edit_col_count)):
                current_column = existing_columns[col_idx] if col_idx < len(existing_columns) else {'name': f'Column {col_idx + 1}', 'type': 'Text Input'}
                edit_col_name = st.text_input(
                    f'Column {col_idx + 1} header',
                    value=current_column.get('name', f'Column {col_idx + 1}'),
                    key=f'edit_table_col_name_{selected_idx}_{col_idx}',
                )
                col_type_options = list(TABLE_COLUMN_TYPES)
                default_col_type = current_column.get('type', 'Text Input')
                default_col_type_index = col_type_options.index(default_col_type) if default_col_type in col_type_options else 0
                edit_col_type = st.selectbox(
                    f'Column {col_idx + 1} type',
                    col_type_options,
                    index=default_col_type_index,
                    key=f'edit_table_col_type_{selected_idx}_{col_idx}',
                )
                updated_column = {
                    'name': edit_col_name.strip(),
                    'type': edit_col_type,
                }
                if edit_col_type == 'Dropdown':
                    existing_col_options = current_column.get('options', [])
                    if not isinstance(existing_col_options, list):
                        existing_col_options = []
                    edit_col_options_text = st.text_area(
                        f'Column {col_idx + 1} dropdown options (one per line)',
                        value='\n'.join(str(opt) for opt in existing_col_options),
                        key=f'edit_table_col_options_{selected_idx}_{col_idx}',
                        height=90,
                    )
                    updated_column['options'] = [line.strip() for line in edit_col_options_text.splitlines() if line.strip()]
                edit_table_columns.append(updated_column)

            edit_table_initial_rows = st.number_input(
                'Initial row count in Render tab',
                min_value=1,
                max_value=25,
                value=edit_table_initial_rows,
                key=f'edit_table_initial_rows_{selected_idx}',
            )
            edit_table_default_rows_text = st.text_area(
                'Default rows JSON (optional)',
                value=json.dumps(selected_component.get('default_rows', []), indent=2),
                key=f'edit_table_default_rows_{selected_idx}',
                height=110,
            )
        if _coerce_layout_columns(st.session_state.get('builder_layout_columns', 1)) > 1:
            edit_span = st.slider(
                'Component width (columns)',
                min_value=1,
                max_value=_coerce_layout_columns(st.session_state.get('builder_layout_columns', 1)),
                value=edit_span,
                key=f'edit_component_span_{selected_idx}',
            )
        else:
            st.caption('Component width: full row (1 of 1).')

        action_cols = st.columns(4)
        with action_cols[0]:
            if st.button('✏️ Update', use_container_width=True):
                if not edit_label.strip():
                    st.error('Label cannot be empty.')
                else:
                    has_validation_error = False
                    updated_component = dict(st.session_state.builder_components[selected_idx])
                    updated_component['label'] = edit_label.strip()
                    updated_component['span'] = _coerce_span(
                        edit_span,
                        _coerce_layout_columns(st.session_state.get('builder_layout_columns', 1)),
                        selected_component.get('type'),
                    )
                    if selected_component.get('type') == 'Checkbox':
                        updated_component['default'] = edit_default
                    if selected_component.get('type') in ('Text Input', 'Textarea', 'Signature'):
                        updated_component['default_value'] = str(edit_default_value_text or '')
                    if selected_component.get('type') == 'Date Picker':
                        normalized_edit_date = _normalize_date_default(edit_default_date_text)
                        if edit_default_date_text.strip() and not normalized_edit_date:
                            st.error('Date default must be YYYY-MM-DD.')
                            has_validation_error = True
                        else:
                            updated_component['default_value'] = normalized_edit_date
                    if selected_component.get('type') == 'Dropdown':
                        if not edit_dropdown_options:
                            st.error('Dropdown components require at least one option.')
                            has_validation_error = True
                        else:
                            updated_component['options'] = edit_dropdown_options
                            clean_dropdown_default = edit_dropdown_default_text.strip()
                            if clean_dropdown_default and clean_dropdown_default not in edit_dropdown_options:
                                st.error('Dropdown default value must match one of the options.')
                                has_validation_error = True
                            else:
                                updated_component['default_value'] = clean_dropdown_default or edit_dropdown_options[0]
                    if selected_component.get('type') == 'Table':
                        cleaned_table_columns = []
                        for column in edit_table_columns:
                            col_name = str(column.get('name', '')).strip()
                            col_type = column.get('type')
                            if not col_name:
                                st.error('Every table column must have a header.')
                                has_validation_error = True
                                cleaned_table_columns = []
                                break
                            if col_type not in TABLE_COLUMN_TYPES:
                                st.error(f'Unsupported table column type: {col_type}')
                                has_validation_error = True
                                cleaned_table_columns = []
                                break

                            updated_col = {'name': col_name, 'type': col_type}
                            if col_type == 'Dropdown':
                                col_options = [opt.strip() for opt in column.get('options', []) if opt.strip()]
                                if not col_options:
                                    st.error(f'Dropdown table column "{col_name}" requires at least one option.')
                                    has_validation_error = True
                                    cleaned_table_columns = []
                                    break
                                updated_col['options'] = col_options
                            cleaned_table_columns.append(updated_col)

                        if cleaned_table_columns:
                            updated_component['columns'] = cleaned_table_columns
                            updated_component['initial_rows'] = _coerce_table_rows(edit_table_initial_rows)
                            if edit_table_default_rows_text.strip():
                                try:
                                    parsed_rows = json.loads(edit_table_default_rows_text)
                                    updated_component['default_rows'] = _normalize_table_default_rows(parsed_rows, cleaned_table_columns)
                                except Exception:
                                    st.error('Default rows JSON is invalid.')
                                    has_validation_error = True
                            else:
                                updated_component['default_rows'] = []

                    if (
                        not has_validation_error
                        and (selected_component.get('type') != 'Dropdown' or edit_dropdown_options)
                        and (selected_component.get('type') != 'Table' or updated_component.get('columns'))
                    ):
                        st.session_state.builder_components[selected_idx] = updated_component
                        persist_forms_state()
                        st.success('✅ Updated.')
        with action_cols[1]:
            if st.button('🗑️ Delete', use_container_width=True):
                st.session_state.builder_components.pop(selected_idx)
                persist_forms_state()
                st.success('🗑️ Deleted.')
        with action_cols[2]:
            if st.button('⬆️ Up', use_container_width=True) and selected_idx > 0:
                comps = st.session_state.builder_components
                comps[selected_idx - 1], comps[selected_idx] = comps[selected_idx], comps[selected_idx - 1]
                persist_forms_state()
                st.success('⬆️ Moved up.')
        with action_cols[3]:
            if st.button('⬇️ Down', use_container_width=True) and selected_idx < len(st.session_state.builder_components) - 1:
                comps = st.session_state.builder_components
                comps[selected_idx + 1], comps[selected_idx] = comps[selected_idx], comps[selected_idx + 1]
                persist_forms_state()
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

        live_values = render_components(
            st.session_state.builder_components,
            'live_render',
            form_columns=st.session_state.get('builder_layout_columns', 1),
        )

        st.markdown('---')

        export_name = st.session_state.save_form_name.strip() or active_form_name

        # Validation: warn about empty text fields
        empty_fields = [
            comp.get('label', '')
            for comp in st.session_state.builder_components
            if comp.get('type') in ('Text Input', 'Textarea', 'Signature')
            and not (live_values.get(comp.get('label', ''), '') or '').strip()
        ]
        if empty_fields:
            st.warning(f'⚠️ {len(empty_fields)} field(s) are empty: {", ".join(empty_fields)}. You can still generate the PDF.')

        col1, col2 = st.columns(2)
        with col1:
            if st.button('📄 Generate & Preview PDF', use_container_width=True):
                pdf_data = build_pdf(
                    export_name,
                    st.session_state.builder_components,
                    live_values,
                    form_columns=st.session_state.get('builder_layout_columns', 1),
                )
                st.session_state.generated_pdf_data = pdf_data
                st.session_state.generated_pdf_name = export_name
                show_pdf_preview_modal()
        with col2:
            if st.session_state.generated_pdf_data:
                if st.button('👁️ View Last Preview', use_container_width=True):
                    show_pdf_preview_modal()
