import streamlit as st
from pyhanko.sign import signers
from pyhanko.sign.fields import SigFieldSpec
from pyhanko_certvalidator import ValidationContext
import tempfile
import os

st.title('PDF Sign App')

st.markdown('''Upload a PDF and a PKCS#12 certificate (.p12/.pfx) file to digitally sign your PDF. You will be able to download the signed PDF.''')

uploaded_pdf = st.file_uploader('Upload PDF to Sign', type=['pdf'])
uploaded_p12 = st.file_uploader('Upload PKCS#12 Certificate (.p12/.pfx)', type=['p12', 'pfx'])
p12_password = st.text_input('PKCS#12 Password', type='password')
sign_button = st.button('Sign PDF')

if sign_button:
    if not uploaded_pdf or not uploaded_p12 or not p12_password:
        st.error('Please upload both PDF and Certificate files and enter the certificate password.')
    else:
        try:
            with tempfile.TemporaryDirectory() as tempdir:
                # Save uploaded files to disk
                pdf_path = os.path.join(tempdir, 'input.pdf')
                p12_path = os.path.join(tempdir, 'cert.p12')

                with open(pdf_path, 'wb') as f:
                    f.write(uploaded_pdf.getbuffer())

                with open(p12_path, 'wb') as f:
                    f.write(uploaded_p12.getbuffer())

                # Load signer
                signer = signers.SimpleSigner.load_pkcs12(p12_path, p12_password.encode())

                # Validation context (optional, can customize trust roots)
                val_context = ValidationContext(trust_roots=None)

                output_path = os.path.join(tempdir, 'signed_output.pdf')

                with open(pdf_path, 'rb') as inf, open(output_path, 'wb') as outf:
                    signers.sign_pdf(
                        inf,
                        signer=signer,
                        signature_field_spec=SigFieldSpec(sig_field_name='Signature1'),
                        output=outf,
                        validation_context=val_context
                    )

                # Read signed PDF for download
                with open(output_path, 'rb') as f:
                    signed_pdf_data = f.read()

                st.success('PDF signed successfully!')
                st.download_button('Download Signed PDF', data=signed_pdf_data, file_name='signed_document.pdf', mime='application/pdf')

        except Exception as e:
            st.error(f'Error signing PDF: {e}')

