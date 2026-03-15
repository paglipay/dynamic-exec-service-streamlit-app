import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

st.set_page_config(page_title="Interactive Plotter")
st.title("Interactive Plotter - Build Dynamic Plots")

# Sample data
np.random.seed(0)
data = pd.DataFrame({
    'x': np.linspace(0, 10, 100),
    'y1': np.sin(np.linspace(0, 10, 100)),
    'y2': np.cos(np.linspace(0, 10, 100)),
    'y3': np.random.normal(size=100).cumsum()
})

plot_type = st.selectbox("Select Plot Type", ["Line", "Scatter", "Bar"])

cols = st.multiselect("Select columns to plot", options=['y1', 'y2', 'y3'], default=['y1'])

if cols:
    fig, ax = plt.subplots()
    for col in cols:
        if plot_type == "Line":
            ax.plot(data['x'], data[col], label=col)
        elif plot_type == "Scatter":
            ax.scatter(data['x'], data[col], label=col)
        elif plot_type == "Bar":
            ax.bar(data['x'], data[col], label=col)
    ax.legend()
    st.pyplot(fig)
else:
    st.info("Select columns to plot.")
