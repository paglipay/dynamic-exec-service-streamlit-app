import os
import tempfile
import json
import base64
import inspect
from datetime import datetime, timezone
from email.message import EmailMessage
from io import BytesIO
from urllib.parse import urlparse, unquote

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
    email_recipients_text = form_data.get('email_recipients_text', '')
    email_optional_message = form_data.get('email_optional_message', '')

    if not isinstance(components, list):
        components = []
    if not isinstance(email_recipients_text, str):
        email_recipients_text = ''
    if not isinstance(email_optional_message, str):
        email_optional_message = ''

    return {
        'components': list(components),
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
                st.session_state.email_recipients_text, st.session_state.email_optional_message = get_form_email_settings(active_form)
            else:
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
        st.session_state.email_recipients_text, st.session_state.email_optional_message = get_form_email_settings(form)


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

    imported_recipients = payload.get('email_recipients_text', '')
    imported_message = payload.get('email_optional_message', '')
    if not isinstance(imported_recipients, str):
        imported_recipients = ''
    if not isinstance(imported_message, str):
        imported_message = ''

    return imported_name.strip(), cleaned, imported_recipients, imported_message


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

    button_col1, button_col2 = st.columns(2)
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
                imported_name, imported_components, imported_recipients, imported_message = parse_imported_form(import_file.getvalue())
                target_name = import_target_name.strip() or imported_name or f"imported_form_{st.session_state.temp_form_counter}"
                if not imported_name and not import_target_name.strip():
                    st.session_state.temp_form_counter += 1
                st.session_state.forms[target_name] = normalize_form_data({
                    'components': imported_components,
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
