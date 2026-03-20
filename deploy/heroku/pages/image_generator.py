import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter
import io
from _auth_guard import require_authentication

st.set_page_config(page_title="Image Generator or Editor")
require_authentication("Image Generator or Editor")
st.title("AI Image Generator and Editor")

mode = st.radio("Select mode", ["Generate Image from Prompt", "Upload and Edit Image"])

if mode == "Generate Image from Prompt":
    prompt = st.text_input("Enter image prompt:")
    if st.button("Generate Image") and prompt:
        st.info("Generating image... (this is a placeholder, integrate AI generation as needed)")
        # Here you would integrate AI image generation API calls
        st.image("https://via.placeholder.com/400x300.png?text=Generated+Image", caption=prompt)

elif mode == "Upload and Edit Image":
    uploaded_file = st.file_uploader("Upload an image", type=["png", "jpg", "jpeg"])
    if uploaded_file:
        image = Image.open(uploaded_file)
        st.image(image, caption="Uploaded Image", use_column_width=True)

        enhance_type = st.selectbox("Enhance", ["None", "Brightness", "Contrast", "Sharpness", "Blur"])

        if enhance_type == "Brightness":
            factor = st.slider("Brightness Factor", 0.1, 3.0, 1.0)
            enhancer = ImageEnhance.Brightness(image)
            image = enhancer.enhance(factor)
        elif enhance_type == "Contrast":
            factor = st.slider("Contrast Factor", 0.1, 3.0, 1.0)
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(factor)
        elif enhance_type == "Sharpness":
            factor = st.slider("Sharpness Factor", 0.1, 3.0, 1.0)
            enhancer = ImageEnhance.Sharpness(image)
            image = enhancer.enhance(factor)
        elif enhance_type == "Blur":
            radius = st.slider("Blur Radius", 0, 5, 0)
            image = image.filter(ImageFilter.GaussianBlur(radius))

        st.image(image, caption="Edited Image", use_column_width=True)
