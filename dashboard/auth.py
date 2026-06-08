"""
auth.py — Sesión persistente del dashboard (cookie firmada)
"""
import hmac
import hashlib
import os
import time
from datetime import datetime, timedelta

import streamlit as st
import extra_streamlit_components as stx

COOKIE_NAME = "nw_dashboard_auth"
SESSION_DAYS = int(os.getenv("DASHBOARD_SESSION_DAYS", "30"))


def get_cookie_manager():
    """Un CookieManager por sesión de Streamlit (no usar @st.cache_*: crea widgets)."""
    if "nw_cookie_manager" not in st.session_state:
        st.session_state.nw_cookie_manager = stx.CookieManager(key="nw_dashboard_cookies")
    return st.session_state.nw_cookie_manager


def _create_token(password: str) -> str:
    expiry = int(time.time()) + SESSION_DAYS * 86400
    sig = hmac.new(
        password.encode(), str(expiry).encode(), hashlib.sha256
    ).hexdigest()
    return f"{expiry}.{sig}"


def _verify_token(token: str, password: str) -> bool:
    try:
        expiry_str, sig = token.split(".", 1)
        if time.time() > int(expiry_str):
            return False
        expected = hmac.new(
            password.encode(), expiry_str.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def _save_cookie_token(cookie_manager, password: str) -> None:
    token = _create_token(password)
    expires = datetime.now() + timedelta(days=SESSION_DAYS)
    cookie_manager.set(
        COOKIE_NAME, token,
        expires_at=expires,
        key="nw_save_auth_cookie",
    )


def clear_session(cookie_manager) -> None:
    cookie_manager.delete(COOKIE_NAME, key="nw_delete_auth_cookie")
    st.session_state.pop("authenticated", None)


def check_auth() -> bool:
    """Devuelve True si el usuario está autenticado."""
    password = os.getenv("DASHBOARD_PASSWORD", "")
    if not password:
        return True

    cookie_manager = get_cookie_manager()
    cookies = cookie_manager.get_all()
    if cookies is None:
        st.stop()

    token = cookies.get(COOKIE_NAME)

    if token and _verify_token(token, password):
        st.session_state["authenticated"] = True
        return True

    if st.session_state.get("authenticated"):
        _save_cookie_token(cookie_manager, password)
        return True

    st.title("Nextwaves Bot Dashboard")
    st.caption(f"La sesión se mantiene {SESSION_DAYS} días en este dispositivo.")
    entered = st.text_input("Contraseña del dashboard", type="password")
    if st.button("Entrar", type="primary"):
        if entered == password:
            st.session_state["authenticated"] = True
            _save_cookie_token(cookie_manager, password)
            st.rerun()
        else:
            st.error("Contraseña incorrecta")
    return False
