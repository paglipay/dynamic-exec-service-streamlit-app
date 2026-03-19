import streamlit as st
from pyhanko.sign import signers
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
import tempfile
import os
import inspect
from datetime import datetime, timedelta, UTC

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID


def create_ephemeral_pkcs12() -> bytes:
    """Generate a temporary self-signed certificate bundle for signing."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, 'US'),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'Dynamic Exec Service'),
            x509.NameAttribute(NameOID.COMMON_NAME, 'Auto Generated PDF Signer'),
        ]
    )

    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    return pkcs12.serialize_key_and_certificates(
        name=b'auto-generated-pdf-signer',
        key=private_key,
        cert=certificate,
        cas=None,
        encryption_algorithm=serialization.NoEncryption(),
    )


def create_incremental_writer_with_hybrid_support(input_stream):
    """Create an incremental writer with hybrid-xref support when available."""
    parameters = inspect.signature(IncrementalPdfFileWriter).parameters
    kwargs = {}

    # Older/newer pyHanko versions expose different constructor options.
    if 'strict' in parameters:
        kwargs['strict'] = False
    if 'allow_hybrid_xrefs' in parameters:
        kwargs['allow_hybrid_xrefs'] = True
    if 'reader_kwargs' in parameters:
        kwargs['reader_kwargs'] = {'strict': False, 'allow_hybrid_xrefs': True}

    return IncrementalPdfFileWriter(input_stream, **kwargs)


def load_signer_from_pkcs12(p12_path: str, password: bytes | None):
    """Load a pyHanko signer with compatibility across pyHanko versions."""
    load_fn = signers.SimpleSigner.load_pkcs12
    parameters = inspect.signature(load_fn).parameters

    # pyHanko signatures differ across versions, so prefer keyword args.
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

    # Legacy fallback where passphrase may be positional.
    signer = load_fn(p12_path, password)
    if signer is None and password is None:
        signer = load_fn(p12_path, b'')
    return signer

st.title('PDF Sign App')

st.markdown('''Upload a PDF and optionally a PKCS#12 certificate (.p12/.pfx) file to digitally sign your PDF. If you do not upload a certificate, an auto-generated one is used for this session.''')

uploaded_pdf = st.file_uploader('Upload PDF to Sign', type=['pdf'])
uploaded_p12 = st.file_uploader('Upload PKCS#12 Certificate (.p12/.pfx)', type=['p12', 'pfx'])
p12_password = st.text_input('PKCS#12 Password', type='password')
sign_button = st.button('Sign PDF')

if sign_button:
    if not uploaded_pdf:
        st.error('Please upload a PDF file to sign.')
    else:
        try:
            with tempfile.TemporaryDirectory() as tempdir:
                # Save uploaded files to disk
                pdf_path = os.path.join(tempdir, 'input.pdf')
                p12_path = os.path.join(tempdir, 'cert.p12')
                # Empty password means an unencrypted PKCS#12 bundle.
                p12_load_password = p12_password.encode() if p12_password else None

                with open(pdf_path, 'wb') as f:
                    f.write(uploaded_pdf.getbuffer())

                if uploaded_p12:
                    with open(p12_path, 'wb') as f:
                        f.write(uploaded_p12.getbuffer())
                else:
                    with open(p12_path, 'wb') as f:
                        f.write(create_ephemeral_pkcs12())
                    st.info('No certificate uploaded. Using an auto-generated self-signed certificate for this signing operation.')

                # Load signer
                signer = load_signer_from_pkcs12(p12_path, p12_load_password)
                if signer is None:
                    raise ValueError(
                        'Unable to load signing credentials from the PKCS#12 file. '
                        'Ensure the file includes a private key and certificate, and verify the password.'
                    )

                output_path = os.path.join(tempdir, 'signed_output.pdf')

                with open(pdf_path, 'rb') as inf, open(output_path, 'wb') as outf:
                    writer = create_incremental_writer_with_hybrid_support(inf)
                    signature_meta = signers.PdfSignatureMetadata(field_name='Signature1')
                    pdf_signer = signers.PdfSigner(signature_meta=signature_meta, signer=signer)
                    pdf_signer.sign_pdf(writer, output=outf)

                # Read signed PDF for download
                with open(output_path, 'rb') as f:
                    signed_pdf_data = f.read()

                st.success('PDF signed successfully!')
                st.download_button('Download Signed PDF', data=signed_pdf_data, file_name='signed_document.pdf', mime='application/pdf')

        except Exception as e:
            st.error(f'Error signing PDF: {e}')

