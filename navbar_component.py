import streamlit as st
from datetime import datetime
from typing import Optional
from utils.chat_store import ChatSession


def render_navbar(active_chat: Optional[ChatSession], browser_time: str, browser_hour: Optional[int]):
    """
    Text-only navbar (fixed at top). No sidebar toggle, no floating buttons.
    """
    msg_count = len(active_chat.messages) if active_chat else 0

    # Fallback to server time if browser time isn't available
    now = datetime.now()
    time_display = browser_time or now.strftime("%I:%M:%S %p")
    hour = browser_hour if browser_hour is not None else now.hour
    vibe = (
        "Wake ☕ suffer" if hour < 12
        else ("Slave 🔗 routine" if hour < 18 else "Cry 🌙 repeat")
    )

    # ---- Styles ----
    st.markdown(
        """
        <style>
          :root { --dark-nav-height: 50px; }

          /* Simple text-only navbar */
          #dark-navbar {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            min-height: var(--dark-nav-height);
            display: flex;
            align-items: center;
            background: transparent;
            color: white;
            z-index: 999999;
            border-bottom: 1px solid #ddd;
            padding: 10px 20px;
            box-sizing: border-box;
            font-size: 14px;
            backdrop-filter: blur(6px);
          }

          /* Adjust navbar for sidebar presence */
          @media (min-width: 769px) {
            #dark-navbar { left: 21rem; }
          }

          #dark-navbar .dark-flex {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 20px;
            width: 100%;
            font-weight: normal;
          }

          #dark-navbar .dark-item { flex: 1; text-align: center; }

          /* Spacer for main content */
          #dark-nav-spacer { height: var(--dark-nav-height); width: 100%; }

          html { scroll-behavior: smooth; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ---- Navbar + Spacer ----
    st.markdown(
        f"""
        <div id="dark-navbar">
          <div class="dark-flex">
            <div class="dark-item">Time: {time_display}</div>
            <div class="dark-item">Messages: {msg_count}</div>
            <div class="dark-item">Mode: {vibe}</div>
          </div>
        </div>
        <div id="dark-nav-spacer"></div>
        """,
        unsafe_allow_html=True,
    )
