import json
import os
import re
from urllib import error, request

import streamlit as st


def _ensure_sidebar_on_right() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {
            left: auto;
            right: 0;
        }

        [data-testid="stSidebarCollapsedControl"] {
            left: auto;
            right: 0.5rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _assistant_reply(message: str, page_name: str) -> str:
    prompt = message.strip()
    lower = prompt.lower()

    if not prompt:
        return "Please type a question and click Send."

    if re.search(r"\b(help|how|guide|what can you do)\b", lower):
        return (
            f"I can help with the {page_name} page. Ask me about inputs, outputs, "
            "filters, naming patterns, or troubleshooting steps."
        )

    if re.search(r"\b(upload|file|csv|excel|xlsx|template)\b", lower):
        return (
            "Start by checking the required upload fields on this page, then verify "
            "column names match the expected placeholders or controls."
        )

    if re.search(r"\b(filter|select|row|checkbox)\b", lower):
        return (
            "Apply filters first, then confirm selected rows/values before running the "
            "action. This prevents generating output from unwanted records."
        )

    if re.search(r"\b(error|failed|traceback|exception|bug)\b", lower):
        return (
            "Share the exact error text and what step triggered it. I can help isolate "
            "whether this is input validation, dependency, or runtime logic."
        )

    return (
        f"I received: '{prompt}'. I can guide you through {page_name} workflows, "
        "settings, and common fixes."
    )


def _get_setting(name: str, default: str = "") -> str:
    env_value = os.getenv(name)
    if env_value is not None and str(env_value).strip():
        return str(env_value).strip()

    try:
        secret_value = st.secrets.get(name, "")
        if secret_value is not None and str(secret_value).strip():
            return str(secret_value).strip()
    except Exception:  # noqa: BLE001
        pass

    return default


def _llm_config() -> tuple[str, str, str]:
    api_key = _get_setting("AI_API_KEY") or _get_setting("OPENAI_API_KEY")
    model = _get_setting("AI_MODEL", "gpt-4o-mini")
    base_url = _get_setting("AI_BASE_URL", "https://api.openai.com/v1")
    return api_key, model, base_url.rstrip("/")


def _call_llm(history: list[dict[str, str]], page_name: str) -> tuple[str | None, str | None]:
    api_key, model, base_url = _llm_config()
    if not api_key:
        return None, (
            "AI API key is not configured. Set AI_API_KEY (or OPENAI_API_KEY) "
            "to enable live assistant responses."
        )

    system_prompt = (
        "You are a helpful assistant embedded in a Streamlit application. "
        f"Current page: {page_name}. Give concise, actionable guidance focused "
        "on the current page workflows, inputs, and troubleshooting."
    )

    recent_history = history[-12:]
    messages = [{"role": "system", "content": system_prompt}]
    for item in recent_history:
        role = item.get("role", "user")
        if role not in {"user", "assistant"}:
            continue
        messages.append({"role": role, "content": str(item.get("content", ""))})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
    }

    endpoint = f"{base_url}/chat/completions"
    req = request.Request(
        endpoint,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        data=json.dumps(payload).encode("utf-8"),
    )

    try:
        with request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"].strip()
        if not content:
            return None, "AI returned an empty response."
        return content, None
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        return None, f"AI request failed ({exc.code}): {details or str(exc)}"
    except Exception as exc:  # noqa: BLE001
        return None, f"AI request failed: {exc}"


def render_ai_assistant_panel(page_name: str) -> None:
    _ensure_sidebar_on_right()

    messages_key = f"ai_messages_{page_name}"
    input_key = f"ai_input_{page_name}"

    if messages_key not in st.session_state:
        st.session_state[messages_key] = [
            {
                "role": "assistant",
                "content": (
                    f"Hi, I am your assistant for {page_name}. "
                    "Ask for help with this page anytime."
                ),
            }
        ]

    with st.sidebar:
        st.markdown("### AI Assistant")

        api_key, model, _ = _llm_config()
        if api_key:
            st.caption(f"Live model: {model}")
        else:
            st.caption("Live model disabled: configure AI_API_KEY or OPENAI_API_KEY")

        if st.button("Clear chat", key=f"clear_ai_{page_name}"):
            st.session_state[messages_key] = [
                {
                    "role": "assistant",
                    "content": (
                        f"Chat cleared. I am ready to help with {page_name}."
                    ),
                }
            ]

        history = st.container(height=300)
        with history:
            for msg in st.session_state[messages_key]:
                speaker = "You" if msg["role"] == "user" else "Assistant"
                st.markdown(f"**{speaker}:** {msg['content']}")

        with st.form(key=f"assistant_form_{page_name}", clear_on_submit=True):
            question = st.text_area(
                "Ask a question",
                key=input_key,
                height=80,
                placeholder="Type your question about this page...",
            )
            ask = st.form_submit_button("Send", use_container_width=True)

        if ask and question.strip():
            st.session_state[messages_key].append(
                {"role": "user", "content": question.strip()}
            )

            with st.spinner("Assistant is thinking..."):
                reply, llm_error = _call_llm(st.session_state[messages_key], page_name)

            if llm_error:
                fallback = _assistant_reply(question, page_name)
                reply = f"{fallback}\n\n(Note: {llm_error})"

            st.session_state[messages_key].append(
                {"role": "assistant", "content": reply}
            )
            st.rerun()
