import streamlit as st
import random
import time

# Starting from the top
with st.chat_message("assistant"):
    st.markdown ("Howdy, I'm Paul")
prompt = st.chat_input("Say something")
if prompt:
    st.write(f"User has sent the following prompt: {prompt}")