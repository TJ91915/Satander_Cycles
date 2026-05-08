"""Payments tab — placeholder until the Payments sheet integration ships."""
import streamlit as st


def render() -> None:
    st.subheader("Payments")
    st.info(
        "Coming next iteration — will read from the Payments sheet and "
        "reconcile against the `Final price` column on the Rental Log."
    )
