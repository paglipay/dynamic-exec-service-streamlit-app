import streamlit as st
from _auth_guard import require_authentication

st.set_page_config(page_title="To-Do List App")
require_authentication("To-Do List App")
st.title("Simple To-Do List")

if 'tasks' not in st.session_state:
    st.session_state.tasks = []

# Input for new task
new_task = st.text_input("Enter a new task")

# Add task button
if st.button("Add Task") and new_task:
    st.session_state.tasks.append(new_task)
    st.success(f"Added task: {new_task}")

# Display tasks with checkboxes for completion
if st.session_state.tasks:
    st.write("### Your Tasks")
    completed_tasks = []
    for i, task in enumerate(st.session_state.tasks):
        checked = st.checkbox(task, key=f"task_{i}")
        if checked:
            completed_tasks.append(task)

    # Remove completed tasks button
    if st.button("Remove Completed Tasks"):
        st.session_state.tasks = [t for t in st.session_state.tasks if t not in completed_tasks]
        st.success("Removed completed tasks.")
else:
    st.write("No tasks yet. Add some!")
