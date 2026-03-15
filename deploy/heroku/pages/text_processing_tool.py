import streamlit as st
from textblob import TextBlob, download_corpora
from textblob.exceptions import MissingCorpusError
from _ai_assistant_panel import render_ai_assistant_panel


@st.cache_resource(show_spinner=False)
def ensure_textblob_corpora() -> bool:
    """Download TextBlob corpora once per app process."""
    download_corpora.download_all()
    return True


def render_analysis(blob: TextBlob) -> None:
    sentiment = blob.sentiment

    st.write("### Sentiment Analysis")
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

st.set_page_config(page_title="Text Processing Tool")
render_ai_assistant_panel("Text Processing Tool")
st.title("Text Processing Tool")
st.write("Perform text analytics, sentiment analysis, and summarization.")

text = st.text_area("Enter text to analyze")

if text:
    blob = TextBlob(text)
    try:
        render_analysis(blob)
    except MissingCorpusError:
        with st.spinner("Downloading required NLP corpora (first run only)..."):
            ensure_textblob_corpora()
        try:
            blob = TextBlob(text)
            render_analysis(blob)
            st.success("NLP corpora downloaded successfully.")
        except MissingCorpusError:
            st.error(
                "Required NLP corpora are still unavailable. "
                "Please redeploy or restart the app and try again."
            )
else:
    st.info("Enter some text to begin analysis.")
