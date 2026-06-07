import streamlit as st
import random
import time

st.set_page_config(page_title="Cloud Status", page_icon="☁️", layout="centered")

st.title("Cloud Status Dashboard")
st.write("Monitor cloud services and system health in a simple Streamlit app.")

services = [
    "API Gateway",
    "Authentication",
    "Database",
    "Message Queue",
    "File Storage",
    "Monitoring",
    "Background Workers",
]

status_options = ["Online", "Degraded", "Offline"]

with st.expander("Latest status snapshot"):
    for service in services:
        status = random.choice(status_options)
        emoji = "✅" if status == "Online" else "⚠️" if status == "Degraded" else "⛔"
        st.markdown(f"**{service}**: {emoji} {status}")

st.markdown("---")

st.subheader("Service health overview")
status_counts = {
    "Online": sum(1 for _ in services if random.choice(status_options) == "Online"),
    "Degraded": sum(1 for _ in services if random.choice(status_options) == "Degraded"),
    "Offline": sum(1 for _ in services if random.choice(status_options) == "Offline"),
}

st.bar_chart(status_counts)

st.write("Updated: ", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
