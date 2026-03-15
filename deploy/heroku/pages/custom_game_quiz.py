import streamlit as st

st.set_page_config(page_title="Custom Game Quiz")
st.title("Interactive Quiz Game")

questions = [
    {"question": "What is the capital of France?", "options": ["Paris", "London", "Berlin", "Madrid"], "answer": "Paris"},
    {"question": "Which planet is known as the Red Planet?", "options": ["Earth", "Venus", "Mars", "Jupiter"], "answer": "Mars"},
    {"question": "Who wrote 'Hamlet'?", "options": ["Charles Dickens", "William Shakespeare", "Mark Twain", "Jane Austen"], "answer": "William Shakespeare"}
]

score = 0

for i, q in enumerate(questions):
    st.write(f"Q{i+1}: {q['question']}")
    user_answer = st.radio("Select your answer", q['options'], key=f"q{i}")
    if user_answer == q['answer']:
        score += 1

st.write(f"### Your score: {score} / {len(questions)}")
