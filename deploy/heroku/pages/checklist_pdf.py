import streamlit as st
import json
import tempfile
import os
import inspect
from io import BytesIO
from pyhanko.sign import signers
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

st.title('Build a Checklist Form to PDF Sign App')


def trigger_rerun():
    # Streamlit >=1.27 uses st.rerun(); older versions expose experimental_rerun.
    if hasattr(st, 'rerun'):
        st.rerun()
    elif hasattr(st, 'experimental_rerun'):
        st.experimental_rerun()


def create_incremental_writer_with_hybrid_support(input_stream):
    parameters = inspect.signature(IncrementalPdfFileWriter).parameters
    kwargs = {}

    if 'strict' in parameters:
        kwargs['strict'] = False
    if 'allow_hybrid_xrefs' in parameters:
        kwargs['allow_hybrid_xrefs'] = True
    if 'reader_kwargs' in parameters:
        kwargs['reader_kwargs'] = {'strict': False, 'allow_hybrid_xrefs': True}

    return IncrementalPdfFileWriter(input_stream, **kwargs)


def load_signer_from_pkcs12(p12_path: str, password: bytes | None):
    load_fn = signers.SimpleSigner.load_pkcs12
    parameters = inspect.signature(load_fn).parameters

    if 'passphrase' in parameters:
        signer = load_fn(p12_path, passphrase=password)
        if signer is None and password is None:
            signer = load_fn(p12_path, passphrase=b'')
        return signer

    if 'pfx_passphrase' in parameters:
        signer = load_fn(p12_path, pfx_passphrase=password)
        if signer is None and password is None:
            signer = load_fn(p12_path, pfx_passphrase=b'')
        return signer

    signer = load_fn(p12_path, password)
    if signer is None and password is None:
        signer = load_fn(p12_path, b'')
    return signer


def ensure_space(c, y, needed_height, page_height):
    if y - needed_height < 50:
        c.showPage()
        c.setFont('Helvetica', 12)
        return page_height - 50
    return y

# Initialize session state for forms storage
if 'forms' not in st.session_state:
    st.session_state.forms = {}

# Sidebar: Select or create new form
st.sidebar.header('Manage Forms')
form_names = list(st.session_state.forms.keys())
selected_form = st.sidebar.selectbox('Select a form to edit', [''] + form_names)

new_form_name = st.sidebar.text_input('Or enter a name for new form')
create_new = st.sidebar.button('Create New Form')

def reset_form_builder():
    st.session_state['input_fields'] = []
    st.session_state['text_fields'] = []
    st.session_state['textarea_fields'] = []
    st.session_state['image_fields'] = []
    st.session_state['checkbox_fields'] = []

if create_new and new_form_name:
    if new_form_name in st.session_state.forms:
        st.sidebar.error('Form name already exists!')
    else:
        reset_form_builder()
        st.session_state.forms[new_form_name] = {
            'inputs': [],
            'texts': [],
            'textareas': [],
            'images': [],
            'checkboxes': []
        }
        st.session_state['_builder_form'] = new_form_name
        st.sidebar.success(f'Created form "{new_form_name}"')
        trigger_rerun()

if selected_form:
    form_data = st.session_state.forms[selected_form]
else:
    form_data = None

# Initialize form builder state
if 'input_fields' not in st.session_state:
    st.session_state.input_fields = []
if 'text_fields' not in st.session_state:
    st.session_state.text_fields = []
if 'textarea_fields' not in st.session_state:
    st.session_state.textarea_fields = []
if 'image_fields' not in st.session_state:
    st.session_state.image_fields = []
if 'checkbox_fields' not in st.session_state:
    st.session_state.checkbox_fields = []

builder_form = selected_form if selected_form else new_form_name
if form_data and st.session_state.get('_builder_form') != selected_form:
    st.session_state.input_fields = list(form_data.get('inputs', []))
    st.session_state.text_fields = list(form_data.get('texts', []))
    st.session_state.textarea_fields = list(form_data.get('textareas', []))
    st.session_state.image_fields = list(form_data.get('images', []))
    st.session_state.checkbox_fields = list(form_data.get('checkboxes', []))
    st.session_state['_builder_form'] = selected_form
elif not form_data and builder_form == new_form_name and new_form_name and st.session_state.get('_builder_form') != new_form_name:
    reset_form_builder()
    st.session_state['_builder_form'] = new_form_name

st.header('Form Builder')

add_element = st.selectbox('Add form element', ['Text', 'Text Input', 'Textarea', 'Image Upload', 'Checkbox'])

if add_element == 'Text':
    text_label = st.text_input('Enter text to display')
    if st.button('Add Text') and text_label:
        st.session_state.text_fields.append({'label': text_label})
        trigger_rerun()

if add_element == 'Text Input':
    input_label = st.text_input('Input field label')
    if st.button('Add Input Field') and input_label:
        st.session_state.input_fields.append({'label': input_label})
        trigger_rerun()

if add_element == 'Textarea':
    textarea_label = st.text_input('Textarea label')
    if st.button('Add Textarea') and textarea_label:
        st.session_state.textarea_fields.append({'label': textarea_label})
        trigger_rerun()

if add_element == 'Image Upload':
    image_label = st.text_input('Image field label')
    if st.button('Add Image Upload') and image_label:
        st.session_state.image_fields.append({'label': image_label})
        trigger_rerun()

if add_element == 'Checkbox':
    checkbox_label = st.text_input('Checkbox label')
    checkbox_default = st.checkbox('Default checked')
    if st.button('Add Checkbox') and checkbox_label:
        st.session_state.checkbox_fields.append({'label': checkbox_label, 'default': checkbox_default})
        trigger_rerun()

if selected_form or new_form_name:
    save_name = selected_form if selected_form else new_form_name
    if st.button('Save Form'):
        st.session_state.forms[save_name] = {
            'inputs': st.session_state.input_fields,
            'texts': st.session_state.text_fields,
            'textareas': st.session_state.textarea_fields,
            'images': st.session_state.image_fields,
            'checkboxes': st.session_state.checkbox_fields
        }
        st.success(f'Form "{save_name}" saved!')
        trigger_rerun()

st.header('Render Form')

render_choice = st.selectbox('Select form to render', [''] + list(st.session_state.forms.keys()))

if render_choice:
    render_form = st.session_state.forms[render_choice]

    st.subheader(f'Rendering: {render_choice}')

    # Store inputs
    inputs_data = {}

    for text in render_form['texts']:
        st.markdown(f"**{text['label']}**")

    for idx, inp in enumerate(render_form['inputs']):
        inputs_data[inp['label']] = st.text_input(inp['label'], key=f"input_{render_choice}_{idx}")

    for idx, ta in enumerate(render_form['textareas']):
        inputs_data[ta['label']] = st.text_area(ta['label'], key=f"textarea_{render_choice}_{idx}")

    for idx, img in enumerate(render_form['images']):
        inputs_data[img['label']] = st.file_uploader(f"Upload image for {img['label']}", type=['png','jpg','jpeg'], key=f"img_{render_choice}_{idx}")

    for idx, cb in enumerate(render_form.get('checkboxes', [])):
        inputs_data[cb['label']] = st.checkbox(
            cb['label'],
            value=cb.get('default', False),
            key=f"checkbox_{render_choice}_{idx}"
        )

    st.subheader('Sign PDF Options')
    uploaded_p12 = st.file_uploader('Upload PKCS#12 Certificate (.p12/.pfx)', type=['p12', 'pfx'])
    p12_password = st.text_input('PKCS#12 Password', type='password')

    if st.button('Generate Signed PDF'):
        with tempfile.TemporaryDirectory() as tempdir:
            pdf_path = os.path.join(tempdir, 'output.pdf')

            # Create the PDF
            c = canvas.Canvas(pdf_path, pagesize=letter)
            width, height = letter

            y = height - 50
            c.setFont('Helvetica-Bold', 16)
            c.drawCentredString(width / 2, y, f"Checklist Form: {render_choice}")
            y -= 40

            c.setFont('Helvetica', 12)

            # Draw form fields
            for text in render_form['texts']:
                y = ensure_space(c, y, 20, height)
                c.drawString(50, y, text['label'])
                y -= 20

            for inp in render_form['inputs']:
                y = ensure_space(c, y, 20, height)
                c.drawString(50, y, f"{inp['label']}: {inputs_data.get(inp['label'], '')}")
                y -= 20

            for cb in render_form.get('checkboxes', []):
                y = ensure_space(c, y, 20, height)
                checked_value = 'Yes' if inputs_data.get(cb['label'], False) else 'No'
                c.drawString(50, y, f"{cb['label']}: {checked_value}")
                y -= 20

            for ta in render_form['textareas']:
                y = ensure_space(c, y, 15, height)
                c.drawString(50, y, f"{ta['label']}:")
                y -= 15
                text_content = inputs_data.get(ta['label'], '')
                lines = text_content.split('\n') if text_content else []
                for line in lines:
                    y = ensure_space(c, y, 15, height)
                    c.drawString(70, y, line)
                    y -= 15
                y -= 10

            for img_field in render_form['images']:
                uploaded_img = inputs_data.get(img_field['label'])
                if uploaded_img is not None:
                    try:
                        image = Image.open(uploaded_img)
                        img_width, img_height = image.size
                        aspect = img_height / img_width
                        display_width = 200
                        display_height = display_width * aspect
                        y = ensure_space(c, y, display_height + 20, height)
                        c.drawString(50, y, f"Image: {img_field['label']}")
                        y -= 20
                        c.drawInlineImage(ImageReader(image), 50, y - display_height, width=display_width, height=display_height)
                        y -= display_height + 20
                    except Exception as e:
                        st.error(f"Error processing image for {img_field['label']}: {e}")

            c.save()

            if uploaded_p12 and p12_password:
                # Sign PDF
                try:
                    p12_path = os.path.join(tempdir, 'cert.p12')
                    with open(p12_path, 'wb') as f:
                        f.write(uploaded_p12.getbuffer())

                    p12_load_password = p12_password.encode() if p12_password else None
                    signer = load_signer_from_pkcs12(p12_path, p12_load_password)
                    if signer is None:
                        raise ValueError('Unable to load signing credentials from PKCS#12 file.')

                    signed_pdf_path = os.path.join(tempdir, 'signed_output.pdf')
                    with open(pdf_path, 'rb') as inf, open(signed_pdf_path, 'wb') as outf:
                        writer = create_incremental_writer_with_hybrid_support(inf)
                        signature_meta = signers.PdfSignatureMetadata(field_name='Signature1')
                        pdf_signer = signers.PdfSigner(signature_meta=signature_meta, signer=signer)
                        pdf_signer.sign_pdf(writer, output=outf)
                    with open(signed_pdf_path, 'rb') as f:
                        signed_pdf_data = f.read()
                    st.success('PDF signed successfully!')
                    st.download_button('Download Signed PDF', data=signed_pdf_data, file_name=f'{render_choice}_signed.pdf', mime='application/pdf')

                except Exception as e:
                    st.error(f'Error signing PDF: {e}')
            else:
                # No signing, offer download unsigned PDF
                with open(pdf_path, 'rb') as f:
                    pdf_data = f.read()
                st.warning('No certificate uploaded or password provided. Downloading unsigned PDF.')
                st.download_button('Download PDF', data=pdf_data, file_name=f'{render_choice}_unsigned.pdf', mime='application/pdf')

