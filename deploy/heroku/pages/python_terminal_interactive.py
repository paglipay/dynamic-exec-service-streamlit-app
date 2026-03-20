import streamlit as st
import subprocess
from _auth_guard import require_authentication

require_authentication('Python Terminal App', required_roles=['admin'])
st.title('Python Terminal App')

st.markdown('''This app allows you to run Python scripts interactively as a terminal session.''')

code = st.text_area('Enter your Python script below:', value='''import random

def guessing_game():
    number_to_guess = random.randint(1, 100)
    attempts = 0

    print("Welcome to the Number Guessing Game!")
    print("I'm thinking of a number between 1 and 100.")

    while True:
        guess = input("Enter your guess (or type 'exit' to quit): ")

        if guess.lower() == 'exit':
            print(f"Game exited. The number was {number_to_guess}.")
            break

        if not guess.isdigit():
            print("Please enter a valid number.")
            continue

        guess = int(guess)
        attempts += 1

        if guess < number_to_guess:
            print("Too low. Try again.")
        elif guess > number_to_guess:
            print("Too high. Try again.")
        else:
            print(f"Congratulations! You guessed the number in {attempts} attempts.")
            break

if __name__ == "__main__":
    guessing_game()
''', height=300)

run_button = st.button('Run Script')

if 'terminal_output' not in st.session_state:
    st.session_state.terminal_output = ''

if run_button:
    # Save script to a temporary file
    with open('temp_script.py', 'w') as f:
        f.write(code)

    # Run the script with subprocess and capture output
    try:
        process = subprocess.Popen(['python3', 'temp_script.py'],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   stdin=subprocess.PIPE,
                                   text=True)

        # Stream output interactively
        output = ''
        while True:
            output_line = process.stdout.readline()
            if output_line == '' and process.poll() is not None:
                break
            if output_line:
                output += output_line
                st.session_state.terminal_output += output_line
                st.text_area('Terminal Output', value=st.session_state.terminal_output, height=300)

    except Exception as e:
        st.error(f"Error running script: {e}")

