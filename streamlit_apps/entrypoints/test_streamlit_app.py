import streamlit as st
import pandas as pd
import numpy as np

st.title("Custom PostHog Streamlit App")
st.write("This is a custom uploaded Streamlit app!")

# Add some interactive elements
st.header("Data Visualization")
data = pd.DataFrame({
    'x': np.random.randn(100),
    'y': np.random.randn(100)
})

st.scatter_chart(data)

# Add a sidebar
st.sidebar.header("Controls")
if st.sidebar.button("Generate New Data"):
    st.rerun()

# Add some PostHog integration placeholder
st.header("PostHog Integration")
st.info("This app will have access to PostHog data in future stages.")

# Interactive widgets
st.header("Interactive Elements")
name = st.text_input("What's your name?")
if name:
    st.write(f"Hello, {name}!")

age = st.slider("How old are you?", 0, 100, 25)
st.write(f"You are {age} years old")

if st.button("Click for a surprise!"):
    st.balloons()
    st.success("🎉 Surprise! You got balloons!")
