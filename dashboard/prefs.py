"""
prefs.py — Preferencias del dashboard persistentes en cookie del navegador
"""
import json
from datetime import datetime, timedelta

import streamlit as st

from dashboard.auth import get_cookie_manager, get_all_cookies, invalidate_cookies_cache

PREFS_COOKIE = "nw_dashboard_prefs"
PREFS_DAYS = 365


def _parse_prefs(raw) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def get_prefs() -> dict:
    """Lee preferencias desde cookie (reutiliza la lectura única de auth)."""
    if "nw_dashboard_prefs" in st.session_state:
        return st.session_state["nw_dashboard_prefs"]

    cookies = get_all_cookies()
    if cookies is None:
        st.session_state["nw_dashboard_prefs"] = {}
        return {}

    prefs = _parse_prefs(cookies.get(PREFS_COOKIE))
    st.session_state["nw_dashboard_prefs"] = prefs
    return prefs


def save_prefs(prefs: dict) -> None:
    """Guarda preferencias en cookie del navegador."""
    st.session_state["nw_dashboard_prefs"] = prefs
    cm = get_cookie_manager()
    cm.set(
        PREFS_COOKIE,
        json.dumps(prefs),
        expires_at=datetime.now() + timedelta(days=PREFS_DAYS),
        key="nw_save_dashboard_prefs",
    )
    invalidate_cookies_cache()
