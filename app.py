import os
import random
import streamlit as st
from dotenv import load_dotenv
from typing import Optional
from time import sleep
from datetime import datetime
from utils.azure_client import stream_chat_completion  # Must yield (text, finish_reason)
from utils.chat_store import new_chat, ChatSession
import streamlit.components.v1 as components  # <-- for browser JS

load_dotenv(override=True)

# Streamlit page configuration
st.set_page_config(page_title="Dark AI", page_icon="💬", layout="wide")

# ---------- Session Bootstrapping ----------
if "chats" not in st.session_state:
    st.session_state.chats = {}  # id -> ChatSession
if "active_chat_id" not in st.session_state:
    st.session_state.active_chat_id = None
if "creating_chat" not in st.session_state:
    st.session_state.creating_chat = False
if "auto_greet" not in st.session_state:
    st.session_state.auto_greet = True
if "role_draft" not in st.session_state:
    st.session_state.role_draft = ""  # Holds text while creating a new chat
if "temperature_draft" not in st.session_state:
    st.session_state.temperature_draft = 0.7  # Default temperature
if "top_p_draft" not in st.session_state:
    st.session_state.top_p_draft = 1.0  # Default top_p
if "dark_quote" not in st.session_state:
    st.session_state.dark_quote = None  # Cache the AI-generated quote
if "browser_time" not in st.session_state:
    st.session_state.browser_time = None  # <-- for browser JS time

# ---------- Helper Functions ----------
def set_active(chat_id: str):
    st.session_state.active_chat_id = chat_id

def get_active_chat() -> Optional[ChatSession]:
    cid = st.session_state.active_chat_id
    return st.session_state.chats.get(cid) if cid else None

def show_thinking_animation(placeholder):
    dots = ["Dark Thinking.", "Dark Thinking..", "Dark Thinking..."]
    for _ in range(3):
        for dot in dots:
            placeholder.markdown(f"🌀 **{dot}**")
            sleep(0.2)

def generate_funky_greeting():
    prompt = [
        {"role": "system", "content": "You are a darkly witty AI greeter. Always return 1–2 short sentences with emojis. Make it mischievous, fun, and slightly chaotic."},
        {"role": "user", "content": "Give me one funky dark-humor inspired greeting for a new chat."}
    ]
    chunks = stream_chat_completion(prompt, temperature=0.9, top_p=1.0, max_tokens=60)
    greeting = ""
    for chunk in chunks:
        if isinstance(chunk, tuple):
            text_piece, _ = chunk
        else:
            text_piece = chunk
        greeting += text_piece
    return greeting.strip()

def generate_dark_quote():
    prompt = [
        {"role": "system", "content": "You are a witty assistant that produces short dark humor motivational quotes. Each should be one sentence, clever, and end with a cheeky tone, simple english."},
        {"role": "user", "content": "Give me one dark humor motivational quote, simple english."}
    ]
    chunks = stream_chat_completion(prompt, temperature=0.9, top_p=1.0, max_tokens=50)
    quote_text = ""
    for chunk in chunks:
        if isinstance(chunk, tuple):
            text_piece, _ = chunk
        else:
            text_piece = chunk
        quote_text += text_piece
    return quote_text.strip()

# ---------- Inject JS to get browser time ----------
js_code = """
<script>
const now = new Date();
const hours = now.getHours();
const minutes = now.getMinutes();
const ampm = hours >= 12 ? 'PM' : 'AM';
const hour12 = hours % 12 || 12;
const timeString = hour12 + ":" + String(minutes).padStart(2, '0') + " " + ampm;
window.parent.postMessage({isStreamlitMessage:true, type:'browserTime', time: timeString}, '*');
</script>
"""
components.html(js_code, height=0)

# ---------- Sidebar ----------
with st.sidebar:
    st.title("🌌 Dark AI Assistant")
    st.caption("Your gateway to intelligent conversations.")

    st.button("➕ Start New Chat", on_click=lambda: st.session_state.update({"creating_chat": True, "role_draft": ""}))

    if st.session_state.chats:
        st.markdown("### 🗂️ Chats")
        ids = list(st.session_state.chats.keys())
        if st.session_state.active_chat_id not in ids:
            st.session_state.active_chat_id = ids[0]

        selected = st.selectbox(
            label="Select a conversation",
            options=ids,
            index=ids.index(st.session_state.active_chat_id),
            format_func=lambda x: st.session_state.chats[x].title,
        )
        if selected and selected != st.session_state.active_chat_id:
            set_active(selected)

        act = get_active_chat()
        if act:
            with st.expander("⚙️ Manage Chat"):
                new_title = st.text_input("Rename Chat", value=act.title, key=f"rename_{act.id}")
                col1, col2 = st.columns(2)
                if col1.button("💾 Save"):
                    act.title = new_title[:60]
                    st.rerun()
                if col2.button("🗑️ Delete"):
                    del st.session_state.chats[act.id]
                    st.session_state.active_chat_id = None
                    st.rerun()
    else:
        st.info("No chats yet. Click **Start New Chat** to begin.")

    st.divider()
    st.checkbox("Auto-greet after role is set", value=st.session_state.auto_greet, key="auto_greet")

    # ---------- Dark Humor Motivational Quote ----------
    if not st.session_state.dark_quote:
        st.session_state.dark_quote = generate_dark_quote()
    st.divider()
    st.caption(f"**🔥 Chaos Fuel:** {st.session_state.dark_quote}")

# ---------- Header (Top Bar Left → Right) ----------
active = get_active_chat()
col_time, col_msgs, col_role, col_tokens, col_vibe = st.columns([1, 1, 2, 3, 2])

# --- Display browser time if available ---
with col_time:
    time_display = st.session_state.browser_time or datetime.now().strftime("%I:%M %p")
    st.markdown(f"🕒 **{time_display}**")

with col_msgs:
    msg_count = len(active.messages) if active else 0
    st.markdown(f"💬 **{msg_count}**")

with col_role:
    if active:
        st.markdown(f"🛠️ **{active.role[:15]}...**")

with col_tokens:
    max_tokens = 4000
    used_tokens = sum(len(m["content"].split()) for m in active.messages) if active else 0
    st.progress(min(used_tokens / max_tokens, 1.0))

with col_vibe:
    hour = datetime.now().hour
    if hour < 12:
        vibe = "☕ Morning Vibes"
    elif hour < 18:
        vibe = "🚀 Afternoon Energy"
    else:
        vibe = "🌙 Night Mode"
    st.markdown(vibe)


# ---------- Main Section ----------
st.title("💬 Dark AI Assistant")
st.caption("Your personalized AI-powered assistant.")

# ---- Role Capture Flow ----
if st.session_state.creating_chat:
    st.subheader("Start a New Chat")
    st.caption("Define this chat’s **role** (e.g., Python tutor, Travel planner, Marketing expert).")

    with st.form("create_chat_form", clear_on_submit=False):
        role_input = st.text_area("Assistant Role (System Message)", key="role_draft", height=120, placeholder="You are a helpful assistant.")
        st.slider("Response Creativity (Temperature)", 0.0, 1.0, value=st.session_state.temperature_draft, key="temperature_draft")
        st.slider("Probability Distribution (Top-p)", 0.0, 1.0, value=st.session_state.top_p_draft, key="top_p_draft")
        submitted = st.form_submit_button("✅ Create Chat")

        if submitted and len(role_input.strip()) > 0:
            role_text = st.session_state.role_draft.strip()
            temperature = st.session_state.temperature_draft
            top_p = st.session_state.top_p_draft
            chat = new_chat(role_text)
            chat.temperature = temperature
            chat.top_p = top_p
            st.session_state.chats[chat.id] = chat
            st.session_state.active_chat_id = chat.id
            st.session_state.creating_chat = False
            if st.session_state.auto_greet:
                greeting = generate_funky_greeting()
                chat.messages.append({"role": "assistant", "content": greeting})
            st.rerun()

    if st.button("❌ Cancel"):
        st.session_state.creating_chat = False
        st.rerun()
    st.stop()

# Ensure an active chat exists
if not active:
    st.info("Click **Start New Chat** in the sidebar to begin. The app will first ask for the chat’s role.")
    st.stop()

# Display Role and Settings
st.markdown(f"#### Role: {active.role}")
st.markdown(f"**Temperature:** {active.temperature} | **Top-p:** {active.top_p}")
st.divider()

# Render Chat History
st.markdown("### 📝 Conversation")
for idx, m in enumerate(active.messages):
    if m["role"] == "user":
        with st.chat_message("user"):
            st.markdown(m["content"])
    elif m["role"] == "assistant":
        with st.chat_message("assistant"):
            st.markdown(m["content"])
            # Add download button for each assistant reply
            st.download_button(
                label="⬇️ Download as Markdown",
                data=m["content"],
                file_name=f"assistant_reply_{idx}.md",
                mime="text/markdown",
                key=f"download_{idx}"
            )

st.divider()

# Chat Input
st.markdown("### 💬 Type Your Message")
user_text = st.chat_input("Type your message…")
if user_text:
    active.messages.append({"role": "user", "content": user_text})
    with st.chat_message("user"):
        st.markdown(user_text)

    with st.chat_message("assistant"):
        final_text = ""
        placeholder = st.empty()
        animation_thread = st.empty()
        show_thinking_animation(animation_thread)

        while True:
            req_messages = active.messages_for_model(max_pairs=40)
            if final_text:
                req_messages.append({"role": "user", "content": "continue from where you left off"})

            chunks = stream_chat_completion(
                req_messages,
                temperature=active.temperature,
                top_p=active.top_p,
                max_tokens=None,
            )

            new_chunk, finish_reason = "", None
            for chunk in chunks:
                if isinstance(chunk, tuple):
                    text_piece, finish_reason = chunk
                else:
                    text_piece = chunk
                new_chunk += text_piece
                placeholder.markdown(final_text + new_chunk)
            final_text += new_chunk
            if finish_reason == "length":
                continue
            break

        active.messages.append({"role": "assistant", "content": final_text})
        placeholder.markdown(final_text)
        # Add download button immediately for the new reply
        st.download_button(
            label="⬇️ Download as Markdown",
            data=final_text,
            file_name=f"assistant_reply_{len(active.messages)}.md",
            mime="text/markdown",
            key=f"download_{len(active.messages)}"
        )
        animation_thread.empty()
