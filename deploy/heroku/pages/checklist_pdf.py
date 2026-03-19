import streamlit as st
import json
import tempfile
import os
from io import BytesIO
from pyhanko.sign import signers
from pyhanko.sign.fields import SigFieldSpec
from pyhanko_certvalidator import ValidationContext
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

st.title('Build a Checklist Form to PDF Sign App')

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

if create_new and new_form_name:
    if new_form_name in st.session_state.forms:
        st.sidebar.error('Form name already exists!')
    else:
        st.session_state.forms[new_form_name] = {'inputs': [], 'texts': [], 'textareas': [], 'images': []}
        st.sidebar.success(f'Created form "{new_form_name}"')
        st.experimental_rerun()

if selected_form:
    form_data = st.session_state.forms[selected_form]
else:
    form_data = None

# Initialize form builder state
if 'input_fields' not in st.session_state:
    st.session_state.input_fields = form_data['inputs'] if form_data else []
if 'text_fields' not in st.session_state:
    st.session_state.text_fields = form_data['texts'] if form_data else []
if 'textarea_fields' not in st.session_state:
    st.session_state.textarea_fields = form_data['textareas'] if form_data else []
if 'image_fields' not in st.session_state:
    st.session_state.image_fields = form_data['images'] if form_data else []

st.header('Form Builder')

add_element = st.selectbox('Add form element', ['Text', 'Text Input', 'Textarea', 'Image Upload'])

if add_element == 'Text':
    text_label = st.text_input('Enter text to display')
    if st.button('Add Text') and text_label:
        st.session_state.text_fields.append({'label': text_label})
        st.experimental_rerun()

if add_element == 'Text Input':
    input_label = st.text_input('Input field label')
    if st.button('Add Input Field') and input_label:
        st.session_state.input_fields.append({'label': input_label})
        st.experimental_rerun()

if add_element == 'Textarea':
    textarea_label = st.text_input('Textarea label')
    if st.button('Add Textarea') and textarea_label:
        st.session_state.textarea_fields.append({'label': textarea_label})
        st.experimental_rerun()

if add_element == 'Image Upload':
    image_label = st.text_input('Image field label')
    if st.button('Add Image Upload') and image_label:
        st.session_state.image_fields.append({'label': image_label})
        st.experimental_rerun()

if selected_form or new_form_name:
    save_name = selected_form if selected_form else new_form_name
    if st.button('Save Form'):
        st.session_state.forms[save_name] = {
            'inputs': st.session_state.input_fields,
            'texts': st.session_state.text_fields,
            'textareas': st.session_state.textarea_fields,
            'images': st.session_state.image_fields
        }
        st.success(f'Form "{save_name}" saved!')
        st.experimental_rerun()

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
                c.drawString(50, y, text['label'])
                y -= 20

            for inp in render_form['inputs']:
                c.drawString(50, y, f"{inp['label']}: {inputs_data.get(inp['label'], '')}")
                y -= 20

            for ta in render_form['textareas']:
                c.drawString(50, y, f"{ta['label']}:")
                y -= 15
                text_content = inputs_data.get(ta['label'], '')
                lines = text_content.split('\n') if text_content else []
                for line in lines:
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
                        if y - display_height < 50:
                            c.showPage()
                            y = height - 50
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
                    signer = signers.SimpleSigner.load_pkcs12(uploaded_p12, p12_password.encode())
                    val_context = ValidationContext(trust_roots=None)
                    signed_pdf_path = os.path.join(tempdir, 'signed_output.pdf')
                    with open(pdf_path, 'rb') as inf, open(signed_pdf_path, 'wb') as outf:
                        signers.sign_pdf(
                            inf,
                            signer=signer,
                            signature_field_spec=SigFieldSpec(sig_field_name='Signature1'),
                            output=outf,
                            validation_context=val_context
                        )
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

