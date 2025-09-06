import os
import json
import streamlit as st
from dotenv import load_dotenv
from typing import Optional, Dict, Any, List
from time import sleep
from datetime import datetime

from utils.azure_client import stream_chat_completion  # Must yield (text, finish_reason)
from utils.chat_store import new_chat, ChatSession
from streamlit_js_eval import streamlit_js_eval  # for browser local time

# Import Navbar Component
from navbar_component import render_navbar

# NEW: web search helper
from utils.web_search import web_search, format_results_for_prompt

load_dotenv(override=True)

# -------------------- Page config --------------------
st.set_page_config(page_title="Dark AI", page_icon="💬", layout="wide")

# -------------------- Global compact styling --------------------
st.markdown(
    """
    <style>
      /* make controls compact & tidy */
      .compact .stMarkdown p { margin-bottom: .3rem; }
      .compact .stSelectbox label, .compact .stSlider label, .compact .stCheckbox label { 
        font-size: 0.9rem; 
        margin-bottom: .2rem;
      }
      .compact [data-baseweb="select"] { min-height: 34px; }
      .compact .stCheckbox > label { display: flex; align-items: center; gap: .35rem; }
      .compact .stSlider [data-baseweb="slider"] { margin-top: .35rem; margin-bottom: .2rem; }
      .compact .stSlider div[role="slider"] { height: 12px; }
      .compact .stSlider .st-c9 { padding-top: 0 !important; }
      .compact .stButton button { padding: .25rem .6rem; font-size: 0.9rem; }
      .tight-col { padding-right: .5rem; }
      .st-emotion-cache-16idsys p { margin-bottom: .35rem; } /* chat body spacing */
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------- Session Bootstrapping --------------------
if "chats" not in st.session_state:
    st.session_state.chats = {}  # id -> ChatSession
if "active_chat_id" not in st.session_state:
    st.session_state.active_chat_id = None
if "creating_chat" not in st.session_state:
    st.session_state.creating_chat = False
if "auto_greet" not in st.session_state:
    st.session_state.auto_greet = True
if "role_draft" not in st.session_state:
    st.session_state.role_draft = ""
if "dark_quote" not in st.session_state:
    st.session_state.dark_quote = None
if "browser_time" not in st.session_state:
    st.session_state.browser_time = None
if "browser_hour" not in st.session_state:
    st.session_state.browser_hour = None
# Clarification state per chat
if "clarify_state" not in st.session_state:
    st.session_state.clarify_state = {}  # { chat_id: {"awaiting": bool, "questions": list[str], "asked_at": str } }
# Developer debug toggle (hidden by default)
if "dev_show_plan" not in st.session_state:
    st.session_state.dev_show_plan = False

# -------------------- Helpers --------------------
def set_active(chat_id: str):
    st.session_state.active_chat_id = chat_id

def get_active_chat() -> Optional[ChatSession]:
    cid = st.session_state.active_chat_id
    return st.session_state.chats.get(cid) if cid else None

def show_thinking_animation(ph):
    dots = ["Dark Thinking.", "Dark Thinking..", "Dark Thinking..."]
    for _ in range(3):
        for d in dots:
            ph.markdown(f"🌀 **{d}**")
            sleep(0.2)

# ✅ Old greeting is kept (as requested)
def generate_funky_greeting():
    prompt = [
        {"role": "system", "content": "You are a darkly witty AI greeter. Always return 1–2 short sentences with emojis. Make it mischievous, fun, and slightly chaotic."},
        {"role": "user", "content": "Give me one funky dark-humor inspired greeting for a new chat."}
    ]
    chunks = stream_chat_completion(prompt, temperature=0.9, top_p=1.0, max_tokens=60)
    out = ""
    for chunk in chunks:
        out += chunk[0] if isinstance(chunk, tuple) else chunk
    return out.strip()

def generate_dark_quote():
    prompt = [
        {"role": "system", "content": "You are a witty assistant that produces short dark humor motivational quotes. Each should be one sentence, clever, and end with a cheeky tone, simple english."},
        {"role": "user", "content": "Give me one dark humor motivational quote, simple english."}
    ]
    chunks = stream_chat_completion(prompt, temperature=0.9, top_p=1.0, max_tokens=50)
    out = ""
    for chunk in chunks:
        out += chunk[0] if isinstance(chunk, tuple) else chunk
    return out.strip()

# ---------- Clarification Gate ----------
def clarity_check(role_text: str, user_text: str) -> dict:
    """
    Decide if more details are required for a precise, role-aligned answer.
    Returns: {"need_info": bool, "questions": [str], "reason": str}
    """
    sys = {
        "role": "system",
        "content": (
            "You are a planner that *only* decides if more details are required for a precise, role-aligned answer.\n"
            "Return STRICT JSON with keys: need_info (boolean), questions (array of up to 4 short questions), reason (string).\n"
            "Ask ONLY for details that materially change the answer. If current info is enough, set need_info=false and questions=[].\n"
            "NO extra text, NO markdown, JSON only."
        ),
    }
    usr = {
        "role": "user",
        "content": (
            f"ROLE:\n{role_text}\n\n"
            f"USER_MESSAGE:\n{user_text}\n\n"
            "Decide if more information is needed to answer accurately within this role."
        ),
    }
    chunks = stream_chat_completion([sys, usr], temperature=0.0, top_p=1.0, max_tokens=180)
    raw = ""
    for ch in chunks:
        raw += ch[0] if isinstance(ch, tuple) else ch
    raw = raw.strip()
    try:
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        need_info = bool(data.get("need_info", False))
        questions = [str(q).strip() for q in (data.get("questions", []) or []) if str(q).strip()]
        reason = str(data.get("reason", "")).strip()
        return {"need_info": need_info, "questions": questions[:4], "reason": reason}
    except Exception:
        return {"need_info": False, "questions": [], "reason": ""}

# ---------- Reasoning Mode: hidden planning / executing / judge ----------
def reason_plan(role_text: str, user_text: str) -> Dict[str, Any]:
    """
    Private planning pass (STRICT JSON). Returns plan dict.
    """
    sys = {
        "role": "system",
        "content": (
            "You are an expert task planner. Produce a compact plan JSON ONLY. "
            "No explanations, no markdown, strictly valid JSON."
        ),
    }
    usr = {
        "role": "user",
        "content": (
            "Fields required:\n"
            "{\n"
            '  "objective": string,\n'
            '  "assumptions": string[],\n'
            '  "steps": string[],\n'
            '  "subproblems": string[],\n'
            '  "data_to_verify": string[],\n'
            '  "web_plan": {"should_search": boolean, "queries": string[]},\n'
            '  "quality_checks": string[]\n'
            "}\n\n"
            f"ROLE:\n{role_text}\n\n"
            f"USER_MESSAGE:\n{user_text}\n\n"
            "Keep lists short and high-signal (<=5 items each)."
        ),
    }
    chunks = stream_chat_completion([sys, usr], temperature=0.3, top_p=1.0, max_tokens=500)
    raw = ""
    for ch in chunks:
        raw += ch[0] if isinstance(ch, tuple) else ch
    raw = raw.strip()
    try:
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        plan = json.loads(raw)
    except Exception:
        plan = {
            "objective": "",
            "assumptions": [],
            "steps": [],
            "subproblems": [],
            "data_to_verify": [],
            "web_plan": {"should_search": False, "queries": []},
            "quality_checks": []
        }
    # Sanity defaults
    plan.setdefault("web_plan", {})
    plan["web_plan"].setdefault("should_search", False)
    plan["web_plan"].setdefault("queries", [])
    return plan

def execute_answer(role_text: str, history_msgs: List[dict], plan: Dict[str, Any], web_sources_block: str, temperature: float, top_p: float) -> str:
    """
    Final user-facing answer pass. Streams internally, returns full text.
    """
    role_guidance = {
        "role": "system",
        "content": (
            f"ROLE (anchor):\n{role_text}\n\n"
            "Follow the plan below to craft a concise, actionable answer in the role's tone. "
            "Do NOT reveal the plan or inner steps. Use citations [n] only if WEB CONTEXT is used."
        ),
    }
    plan_msg = {
        "role": "system",
        "content": f"PLAN JSON:\n{json.dumps(plan, ensure_ascii=False)}"
    }
    msgs = [role_guidance] + history_msgs + [plan_msg]

    if web_sources_block:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msgs.append({
            "role": "system",
            "content": (
                "WEB CONTEXT (use only to support the answer; ignore anything off-role):\n\n"
                f"Retrieved: {timestamp}\n\nWEB SEARCH RESULTS:\n{web_sources_block}\n\n"
                "Cite as [n] matching the numbered source."
            ),
        })

    chunks = stream_chat_completion(
        msgs, temperature=temperature, top_p=top_p, max_tokens=None,
    )
    draft = ""
    for ch in chunks:
        draft += ch[0] if isinstance(ch, tuple) else ch
    return draft.strip()

def judge_answer(role_text: str, draft: str, used_web: bool) -> Dict[str, Any]:
    """
    Hidden judge to catch obvious issues. Returns:
    {"ok": bool, "needs_fix": bool, "issues": [str]}
    """
    sys = {
        "role": "system",
        "content": (
            "You are a strict answer judge. Return STRICT JSON only. "
            "Check role alignment, clarity, factuality, presence of citations if web was used, and basic logical coherence."
        ),
    }
    usr = {
        "role": "user",
        "content": (
            f"ROLE:\n{role_text}\n\n"
            f"USED_WEB: {str(used_web).lower()}\n\n"
            f"ANSWER:\n{draft}\n\n"
            'Return JSON: {"ok": boolean, "needs_fix": boolean, "issues": string[]}. Keep issues short.'
        ),
    }
    chunks = stream_chat_completion([sys, usr], temperature=0.0, top_p=1.0, max_tokens=240)
    raw = ""
    for ch in chunks:
        raw += ch[0] if isinstance(ch, tuple) else ch
    raw = raw.strip()
    try:
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        data.setdefault("ok", True)
        data.setdefault("needs_fix", False)
        data.setdefault("issues", [])
        return data
    except Exception:
        return {"ok": True, "needs_fix": False, "issues": []}

def revise_answer(role_text: str, draft: str, issues: List[str]) -> str:
    """
    One-shot revision to fix judge's issues.
    """
    sys = {
        "role": "system",
        "content": (
            "You are a precise reviser. Produce an improved answer that addresses the listed issues. "
            "Keep the same intent and role tone. Return ONLY the final answer text (no notes)."
        ),
    }
    usr = {
        "role": "user",
        "content": (
            f"ROLE:\n{role_text}\n\n"
            f"ISSUES:\n{json.dumps(issues, ensure_ascii=False)}\n\n"
            f"CURRENT_ANSWER:\n{draft}"
        ),
    }
    chunks = stream_chat_completion([sys, usr], temperature=0.2, top_p=1.0, max_tokens=None)
    fixed = ""
    for ch in chunks:
        fixed += ch[0] if isinstance(ch, tuple) else ch
    return fixed.strip()

# -------------------- Get browser local time (only once) --------------------
if st.session_state.browser_time is None or st.session_state.browser_hour is None:
    user_time = streamlit_js_eval(
        js_expressions="new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit', hour12:true})"
    )
    user_hour = streamlit_js_eval(js_expressions="new Date().getHours()")

    if user_time:
        st.session_state.browser_time = user_time
    if user_hour is not None:
        st.session_state.browser_hour = int(user_hour)

# -------------------- Sidebar --------------------
with st.sidebar:
    st.title("🌌 Dark AI Assistant")
    st.caption("Your gateway to intelligent conversations.")

    # Start New Chat Button
    st.button("➕ Start New Chat", on_click=lambda: st.session_state.update({"creating_chat": True, "role_draft": ""}))

    # Display existing chats
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
            with st.expander("⚙️ Manage Chat", expanded=False):
                new_title = st.text_input("Rename Chat", value=act.title, key=f"rename_{act.id}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("💾 Save"):
                        act.title = new_title[:60]
                        st.rerun()
                with c2:
                    if st.button("🗑️ Delete"):
                        del st.session_state.chats[act.id]
                        st.session_state.active_chat_id = None
                        st.rerun()
    else:
        st.info("No chats yet. Click **Start New Chat** to begin.")

    st.divider()

    # Auto-greet checkbox
    st.checkbox("Auto-greet after role is set", value=st.session_state.auto_greet, key="auto_greet")

    if not st.session_state.dark_quote:
        st.session_state.dark_quote = generate_dark_quote()

    st.markdown("### 🔥 Chaos Fuel")
    st.caption(st.session_state.dark_quote)

# -------------------- Main --------------------
active_chat = get_active_chat()
render_navbar(active_chat, st.session_state.browser_time, st.session_state.browser_hour)

st.title("💬 Dark AI Assistant")
st.caption("Your personalized AI-powered assistant.")

# ---- Role Capture Flow ----
if st.session_state.creating_chat:
    st.subheader("Start a New Chat")
    st.caption("Define this chat’s **role** (e.g., Python tutor, Travel planner, Marketing expert).")

    with st.form("create_chat_form", clear_on_submit=False):
        role_input = st.text_area(
            "Assistant Role (System Message)",
            key="role_draft",
            height=120,
            placeholder="You are a helpful assistant."
        )
        # Compact row for model params
        st.markdown('<div class="compact">', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            temperature = st.slider("Temperature", 0.0, 1.0, 0.7, key="new_temp")
        with c2:
            top_p = st.slider("Top-p", 0.0, 1.0, 1.0, key="new_top_p")
        st.markdown('</div>', unsafe_allow_html=True)

        submitted = st.form_submit_button("✅ Create Chat")

        if submitted and len(role_input.strip()) > 0:
            role_text = st.session_state.role_draft.strip()
            chat = new_chat(role_text)
            chat.temperature = temperature
            chat.top_p = top_p
            # defaults per chat
            chat.use_web_search = True
            chat.web_results_per_query = 5
            chat.web_extract_chars = 900
            chat.reasoning_depth = "Standard"  # Fast | Standard | Deep

            st.session_state.chats[chat.id] = chat
            st.session_state.active_chat_id = chat.id
            st.session_state.creating_chat = False
            # keep the original funky greeter
            if st.session_state.auto_greet:
                greeting = generate_funky_greeting()
                chat.messages.append({"role": "assistant", "content": greeting})
            st.rerun()

    if st.button("❌ Cancel"):
        st.session_state.creating_chat = False
        st.rerun()
    st.stop()

# Ensure an active chat exists
active = get_active_chat()
if not active:
    st.info("Click **Start New Chat** in the sidebar to begin. The app will first ask for the chat’s role.")
    st.stop()

# ---- Display Role and per-chat settings ----
st.markdown(f"#### Role: {active.role}")
st.markdown("> Everything is answered **through this role**. If I need details, I’ll ask first—then proceed once you reply.")
st.divider()

# ---- Compact Settings UI ----
st.markdown('<div class="compact">', unsafe_allow_html=True)

with st.expander("⚙️ Chat Settings", expanded=False):
    # Row 1: Reasoning + Model controls (compact)
    r1c1, r1c2, r1c3 = st.columns([1, 1, 1])
    with r1c1:
        active.reasoning_depth = st.selectbox(
            "Reasoning depth",
            options=["Fast", "Standard", "Deep"],
            index=["Fast", "Standard", "Deep"].index(getattr(active, "reasoning_depth", "Standard")),
            key=f"reasoning_depth_{active.id}",
        )
    with r1c2:
        active.temperature = st.slider("Temperature", 0.0, 1.0, value=active.temperature, key=f"temperature_{active.id}")
    with r1c3:
        active.top_p = st.slider("Top-p", 0.0, 1.0, value=active.top_p, key=f"top_p_{active.id}")

    # Row 2: Web search controls (compact)
    r2c1, r2c2, r2c3 = st.columns([1, 1, 1])
    with r2c1:
        active.use_web_search = st.checkbox(
            "Enable web search",
            value=getattr(active, "use_web_search", True),
            key=f"use_web_search_{active.id}"
        )
    with r2c2:
        if active.use_web_search:
            active.web_results_per_query = st.slider(
                "Results per query", 1, 10,
                value=getattr(active, "web_results_per_query", 5),
                key=f"web_results_per_query_{active.id}"
            )
    with r2c3:
        if active.use_web_search:
            active.web_extract_chars = st.slider(
                "Chars per source", 300, 2000,
                step=50,
                value=getattr(active, "web_extract_chars", 900),
                key=f"web_extract_chars_{active.id}"
            )

st.markdown('</div>', unsafe_allow_html=True)

st.divider()

# ---- Conversation ----
st.markdown("### 📝 Conversation")

st.markdown('<div id="chat-top-anchor"></div>', unsafe_allow_html=True)

for idx, m in enumerate(active.messages):
    if m["role"] == "user":
        with st.chat_message("user"):
            st.markdown(m["content"])
    elif m["role"] == "assistant":
        with st.chat_message("assistant"):
            st.markdown(m["content"])
            st.download_button(
                label="⬇️ Download as Markdown",
                data=m["content"],
                file_name=f"assistant_reply_{idx}.md",
                mime="text/markdown",
                key=f"download_{idx}"
            )

st.markdown('<div id="chat-bottom-anchor"></div>', unsafe_allow_html=True)

st.divider()

# ---- Chat Input ----
st.markdown("### 💬 Type Your Message")
user_text = st.chat_input("Type your message…")

if user_text:
    raw_user_text = user_text
    lowered = raw_user_text.strip().lower()
    if lowered.startswith(("offline:", "no web:", "noweb:")):
        do_web = False
        for prefix in ("offline:", "no web:", "noweb:"):
            if lowered.startswith(prefix):
                user_text = raw_user_text[len(prefix):].strip()
                break
    else:
        do_web = getattr(active, "use_web_search", True)

    # Append user's message to history
    active.messages.append({"role": "user", "content": user_text})
    with st.chat_message("user"):
        st.markdown(user_text)

    # Clarification state for this chat
    chat_clar = st.session_state.clarify_state.get(active.id, {"awaiting": False, "questions": []})

    with st.chat_message("assistant"):
        placeholder = st.empty()
        anim = st.empty()
        show_thinking_animation(anim)

        # -------------------- If awaiting clarifications: proceed directly with reasoning pipeline --------------------
        awaiting = chat_clar.get("awaiting", False)
        if awaiting:
            st.session_state.clarify_state[active.id] = {"awaiting": False, "questions": []}
            # Build history for model (role-anchored)
            role_guidance = {
                "role": "system",
                "content": (
                    f"ROLE (anchor):\n{active.role}\n\n"
                    "Always interpret the request through this ROLE’s lens. "
                    "Use the latest user clarifications to proceed."
                ),
            }
            history_for_model = [role_guidance] + active.messages_for_model(max_pairs=40)

            # Reasoning depth flow
            reasoning_depth = getattr(active, "reasoning_depth", "Standard")
            web_sources_block = ""
            used_web = False

            # PLAN (Standard/Deep)
            if reasoning_depth in ("Standard", "Deep"):
                plan = reason_plan(active.role, user_text)
            else:
                plan = {
                    "objective": "",
                    "assumptions": [],
                    "steps": [],
                    "subproblems": [],
                    "data_to_verify": [],
                    "web_plan": {"should_search": False, "queries": []},
                    "quality_checks": []
                }

            # Optional targeted web search (if enabled AND plan suggests)
            if do_web and plan.get("web_plan", {}).get("should_search") and active.use_web_search:
                all_results = []
                for q in plan["web_plan"].get("queries", [])[:3]:
                    try:
                        all_results.extend(
                            web_search(q, max_results=active.web_results_per_query, extract_chars=active.web_extract_chars)
                        )
                    except Exception as e:
                        st.warning(f"Web search failed: {e}")
                if all_results:
                    with st.expander(f"🔗 Web sources used ({len(all_results)})", expanded=False):
                        for i, r in enumerate(all_results, start=1):
                            st.markdown(f"**[{i}] [{r.title}]({r.url})**")
                            if r.snippet:
                                st.caption(r.snippet)
                            if r.extract:
                                st.markdown(f"> {r.extract}")
                    web_sources_block = format_results_for_prompt(all_results)
                    used_web = True

            # EXECUTE answer
            draft = execute_answer(
                role_text=active.role,
                history_msgs=history_for_model,
                plan=plan,
                web_sources_block=web_sources_block,
                temperature=active.temperature,
                top_p=active.top_p
            )

            final_text = draft
            # DEEP: judge + one-shot revise
            if getattr(active, "reasoning_depth", "Standard") == "Deep":
                judge = judge_answer(active.role, draft, used_web=used_web)
                if judge.get("needs_fix") and judge.get("issues"):
                    final_text = revise_answer(active.role, draft, judge["issues"])

            placeholder.markdown(final_text)
            active.messages.append({"role": "assistant", "content": final_text})
            st.download_button(
                label="⬇️ Download as Markdown",
                data=final_text,
                file_name=f"assistant_reply_{len(active.messages)}.md",
                mime="text/markdown",
                key=f"download_{len(active.messages)}"
            )
            anim.empty()
            st.stop()

        # -------------------- Otherwise, run the Clarification Gate first --------------------
        check = clarity_check(active.role, user_text)
        if check.get("need_info") and check.get("questions"):
            q_list = check["questions"]
            asked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state.clarify_state[active.id] = {"awaiting": True, "questions": q_list, "asked_at": asked_at}

            bullet_qs = "\n".join([f"1) {q_list[0]}"] + [f"{i+1}) {q}" for i, q in enumerate(q_list[1:])]) if q_list else ""
            clarify_msg = (
                "To give you the most accurate, role-aligned answer, I need a few details:\n\n"
                f"{bullet_qs}\n\n"
                "_Reply with the answers (you can be brief)._"
            )
            placeholder.markdown(clarify_msg)
            active.messages.append({"role": "assistant", "content": clarify_msg})
            st.download_button(
                label="⬇️ Download as Markdown",
                data=clarify_msg,
                file_name=f"assistant_reply_{len(active.messages)}.md",
                mime="text/markdown",
                key=f"download_{len(active.messages)}"
            )
            anim.empty()
            st.stop()

        # -------------------- If no clarification needed: Reasoning pipeline --------------------
        # Build history for model (role-anchored)
        role_guidance = {
            "role": "system",
            "content": (
                f"ROLE (anchor):\n{active.role}\n\n"
                "Always interpret the user's request through this ROLE’s lens. "
                "If critical details are missing, ask up to 3 concise questions before answering; "
                "otherwise proceed."
            ),
        }
        history_for_model = [role_guidance] + active.messages_for_model(max_pairs=40)

        # Reasoning depth flow
        reasoning_depth = getattr(active, "reasoning_depth", "Standard")
        web_sources_block = ""
        used_web = False

        # PLAN (Standard/Deep)
        if reasoning_depth in ("Standard", "Deep"):
            plan = reason_plan(active.role, user_text)
        else:
            plan = {
                "objective": "",
                "assumptions": [],
                "steps": [],
                "subproblems": [],
                "data_to_verify": [],
                "web_plan": {"should_search": False, "queries": []},
                "quality_checks": []
            }

        # Optional targeted web search (if enabled AND plan suggests)
        if do_web and plan.get("web_plan", {}).get("should_search") and active.use_web_search:
            all_results = []
            for q in plan["web_plan"].get("queries", [])[:3]:
                try:
                    all_results.extend(
                        web_search(q, max_results=active.web_results_per_query, extract_chars=active.web_extract_chars)
                    )
                except Exception as e:
                    st.warning(f"Web search failed: {e}")
            if all_results:
                with st.expander(f"🔗 Web sources used ({len(all_results)})", expanded=False):
                    for i, r in enumerate(all_results, start=1):
                        st.markdown(f"**[{i}] [{r.title}]({r.url})**")
                        if r.snippet:
                            st.caption(r.snippet)
                        if r.extract:
                            st.markdown(f"> {r.extract}")
                web_sources_block = format_results_for_prompt(all_results)
                used_web = True

        # EXECUTE answer
        draft = execute_answer(
            role_text=active.role,
            history_msgs=history_for_model,
            plan=plan,
            web_sources_block=web_sources_block,
            temperature=active.temperature,
            top_p=active.top_p
        )

        final_text = draft
        # DEEP: judge + one-shot revise
        if reasoning_depth == "Deep":
            judge = judge_answer(active.role, draft, used_web=used_web)
            if judge.get("needs_fix") and judge.get("issues"):
                final_text = revise_answer(active.role, draft, judge["issues"])

        # (Optional) Developer debug: show plan JSON
        if st.session_state.dev_show_plan:
            with st.expander("🧠 Plan (debug)", expanded=False):
                st.code(json.dumps(plan, indent=2, ensure_ascii=False), language="json")

        placeholder.markdown(final_text)
        active.messages.append({"role": "assistant", "content": final_text})
        st.download_button(
            label="⬇️ Download as Markdown",
            data=final_text,
            file_name=f"assistant_reply_{len(active.messages)}.md",
            mime="text/markdown",
            key=f"download_{len(active.messages)}"
        )
        anim.empty()
