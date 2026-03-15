import streamlit as st
from textblob import TextBlob

st.set_page_config(page_title="Text Processing Tool")
st.title("Text Processing Tool")
st.write("Perform text analytics, sentiment analysis, and summarization.")

text = st.text_area("Enter text to analyze")

if text:
    blob = TextBlob(text)

    st.write("### Sentiment Analysis")
    sentiment = blob.sentiment
    st.write(f"Polarity: {sentiment.polarity}")
    st.write(f"Subjectivity: {sentiment.subjectivity}")

    st.write("### Word Count")
    st.write(len(blob.words))

    st.write("### Noun Phrases")
    st.write(blob.noun_phrases)

    # Basic summarization by extracting first few sentences
    st.write("### Summary (first 3 sentences)")
    sentences = blob.sentences
    summary = ' '.join(str(s) for s in sentences[:3])
    st.write(summary)
else:
    st.info("Enter some text to begin analysis.")
