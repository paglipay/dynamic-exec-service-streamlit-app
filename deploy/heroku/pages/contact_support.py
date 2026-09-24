import importlib.util
import json
import os
import sys
from email.message import EmailMessage

import streamlit as st
from _auth_guard import require_authentication

require_authentication("Contact & Support")

# ── Reuse Gmail from checklist_pdf ─────────────────────────────────────────
# checklist_pdf.py already has a fully-featured get_gmail_service() that
# handles OAuth and Service Account auth via the same env variables.
# We import it dynamically so contact_support.py stays independent.

def _load_checklist_module():
    pages_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(pages_dir, "checklist_pdf.py")
    if not os.path.exists(path):
        return None
    if "checklist_pdf" in sys.modules:
        return sys.modules["checklist_pdf"]
    spec = importlib.util.spec_from_file_location("checklist_pdf", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        sys.modules["checklist_pdf"] = mod
        return mod
    except Exception:
        return None

_checklist = _load_checklist_module()
_get_gmail_service = getattr(_checklist, "get_gmail_service", None)

# ── Notification helpers ───────────────────────────────────────────────────

def _get_env(name: str) -> str:
    """Read from env then Streamlit secrets, return '' if absent."""
    val = os.getenv(name, "")
    if val:
        return val.strip()
    try:
        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return ""


def _send_email(to: str, subject: str, body: str) -> str | None:
    """Send via Gmail API (reusing checklist_pdf credentials). Returns error string or None."""
    if not to:
        return None  # no recipient configured — skip silently

    if _get_gmail_service is None:
        return "Gmail module unavailable."

    try:
        gmail_service, sender, _ = _get_gmail_service()
        import base64
        msg = EmailMessage()
        msg["To"] = to
        if sender:
            msg["From"] = sender
        msg["Subject"] = subject
        msg.set_content(body)
        encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        gmail_service.users().messages().send(userId="me", body={"raw": encoded}).execute()
        return None
    except Exception as exc:
        return str(exc)


def _send_slack(webhook_env: str, text: str) -> str | None:
    """POST a message via Slack Incoming Webhook. Returns error or None."""
    import urllib.request

    url = _get_env(webhook_env)
    if not url:
        return None  # not configured

    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status != 200:
                return f"Slack returned HTTP {resp.status}"
        return None
    except Exception as exc:
        return str(exc)

# ── Sidebar section navigation ─────────────────────────────────────────────
st.sidebar.divider()
st.sidebar.markdown(
    '<p style="font-size:0.68rem;font-weight:700;text-transform:uppercase;'
    'letter-spacing:1.5px;color:#999;margin-bottom:6px;">Support</p>',
    unsafe_allow_html=True,
)
section = st.sidebar.radio(
    "Navigate",
    ["🎫 Submit a Ticket", "💼 Contact Sales", "📚 Help Center"],
    label_visibility="collapsed",
    key="_contact_nav",
)

# ── Shared helpers ─────────────────────────────────────────────────────────

def _card_start(title: str, icon: str = "") -> None:
    st.markdown(
        f"""
        <div class="ctk-support-card">
            <div class="ctk-support-card-title">{icon}&nbsp;{title}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    """
    <style>
    .ctk-support-card {
        background: #FAFAF7;
        border: 1.5px solid #E0E0DA;
        border-radius: 12px;
        padding: 18px 22px 8px;
        margin-bottom: 18px;
    }
    .ctk-support-card-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #1C1C1E;
        margin-bottom: 14px;
    }
    .ctk-info-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 0;
        border-bottom: 1px solid #EBEBEB;
    }
    .ctk-info-row:last-child { border-bottom: none; }
    .ctk-info-label {
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        color: #888;
        min-width: 110px;
    }
    .ctk-info-value {
        font-size: 0.88rem;
        color: #1C1C1E;
    }
    .ctk-info-value a { color: #E87722; text-decoration: none; }
    .ctk-info-value a:hover { text-decoration: underline; }
    .ctk-badge {
        display: inline-block;
        font-size: 0.68rem;
        font-weight: 700;
        padding: 2px 10px;
        border-radius: 20px;
        letter-spacing: 0.5px;
    }
    .ctk-badge-green  { background:#D1FAE5; color:#065F46; }
    .ctk-badge-orange { background:#FEF3C7; color:#92400E; }
    .ctk-badge-red    { background:#FEE2E2; color:#991B1B; }
    .ctk-faq-q {
        font-weight: 700;
        color: #1C1C1E;
        padding: 4px 0 2px;
    }
    .ctk-faq-a {
        color: #555;
        font-size: 0.88rem;
        padding-bottom: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ═══════════════════════════════════════════════════════════════════════════
# 1 · SUBMIT A TICKET
# ═══════════════════════════════════════════════════════════════════════════
if section == "🎫 Submit a Ticket":
    st.title("🎫 Submit a Support Ticket")
    st.caption("Our support team typically responds within one business day.")

    col_form, col_info = st.columns([3, 2], gap="large")

    with col_form:
        with st.form("support_ticket_form", clear_on_submit=True):
            name = st.text_input("Your name", placeholder="Jane Smith")
            email = st.text_input("Email address", placeholder="you@example.com")
            subject = st.selectbox(
                "Category",
                [
                    "General question",
                    "Bug or error report",
                    "Feature request",
                    "Account / billing",
                    "Other",
                ],
            )
            priority = st.radio(
                "Priority",
                ["Low", "Medium", "High", "Critical"],
                horizontal=True,
                index=1,
            )
            description = st.text_area(
                "Describe the issue",
                placeholder="Include steps to reproduce, screenshots links, or any relevant details…",
                height=160,
            )
            attachment = st.file_uploader(
                "Attach a file (optional)",
                type=["png", "jpg", "jpeg", "pdf", "txt", "log", "csv"],
                accept_multiple_files=False,
            )
            submitted = st.form_submit_button("Submit Ticket", type="primary", use_container_width=True)

        if submitted:
            errors = []
            if not name.strip():
                errors.append("Name is required.")
            if not email.strip() or "@" not in email:
                errors.append("A valid email address is required.")
            if not description.strip():
                errors.append("Please describe your issue.")
            if errors:
                for e in errors:
                    st.error(e)
            else:
                support_email = _get_env("CTK_SUPPORT_EMAIL")
                email_body = (
                    f"New Support Ticket\n"
                    f"{'─'*40}\n"
                    f"From:        {name} <{email}>\n"
                    f"Category:    {subject}\n"
                    f"Priority:    {priority}\n"
                    f"{'─'*40}\n\n"
                    f"{description}\n"
                )
                slack_text = (
                    f"🎫 *New Support Ticket* [{priority}]\n"
                    f"*From:* {name} ({email})\n"
                    f"*Category:* {subject}\n"
                    f"*Details:* {description[:400]}"
                )

                notify_errors = []
                err = _send_email(support_email, f"[{priority}] Support Ticket – {subject}", email_body)
                if err:
                    notify_errors.append(f"Email: {err}")
                err = _send_slack("CTK_SLACK_SUPPORT_WEBHOOK", slack_text)
                if err:
                    notify_errors.append(f"Slack: {err}")

                st.success(
                    f"✅ Ticket submitted! We'll get back to **{name}** at **{email}** shortly.",
                    icon="✅",
                )
                if notify_errors:
                    st.warning("Ticket recorded, but some notifications failed: " + " | ".join(notify_errors))
                st.balloons()

    with col_info:
        st.markdown(
            """
            <div class="ctk-support-card">
                <div class="ctk-support-card-title">📋 Before You Submit</div>
                <div class="ctk-faq-q">Search the Help Center first</div>
                <div class="ctk-faq-a">Many common questions are already answered under <em>Help Center</em>.</div>
                <div class="ctk-faq-q">Include screenshots</div>
                <div class="ctk-faq-a">Attach a screenshot or log file for faster resolution.</div>
                <div class="ctk-faq-q">Note your browser & OS</div>
                <div class="ctk-faq-a">Include browser version and operating system in your description.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            """
            <div class="ctk-support-card">
                <div class="ctk-support-card-title">⏱️ Response Times</div>
                <div class="ctk-info-row">
                    <span class="ctk-info-label">Low / Medium</span>
                    <span class="ctk-info-value">1–2 business days</span>
                </div>
                <div class="ctk-info-row">
                    <span class="ctk-info-label">High</span>
                    <span class="ctk-info-value">Same business day</span>
                </div>
                <div class="ctk-info-row">
                    <span class="ctk-info-label">Critical</span>
                    <span class="ctk-info-value">Within 4 hours</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ═══════════════════════════════════════════════════════════════════════════
# 2 · CONTACT SALES
# ═══════════════════════════════════════════════════════════════════════════
elif section == "💼 Contact Sales":
    st.title("💼 Contact Sales")
    st.caption("Questions about licensing, pricing, or enterprise plans? We'd love to talk.")

    col_form, col_info = st.columns([3, 2], gap="large")

    with col_form:
        with st.form("sales_contact_form", clear_on_submit=True):
            name = st.text_input("Full name", placeholder="John Contractor")
            company = st.text_input("Company / Organisation", placeholder="Acme Trades Ltd.")
            email = st.text_input("Business email", placeholder="john@acmetrades.com")
            phone = st.text_input("Phone (optional)", placeholder="+1 555 000 0000")
            interest = st.multiselect(
                "I'm interested in…",
                [
                    "Single-user licence",
                    "Team / multi-seat plan",
                    "Enterprise on-premise deployment",
                    "Custom feature development",
                    "Training & onboarding",
                    "Other",
                ],
            )
            message = st.text_area(
                "Tell us about your needs",
                placeholder="Team size, current workflows, timeline…",
                height=130,
            )
            submitted = st.form_submit_button("Send Message", type="primary", use_container_width=True)

        if submitted:
            errors = []
            if not name.strip():
                errors.append("Name is required.")
            if not email.strip() or "@" not in email:
                errors.append("A valid business email is required.")
            if errors:
                for e in errors:
                    st.error(e)
            else:
                sales_email = _get_env("CTK_SALES_EMAIL")
                interests_str = ", ".join(interest) if interest else "Not specified"
                email_body = (
                    f"New Sales Enquiry\n"
                    f"{'─'*40}\n"
                    f"Name:        {name}\n"
                    f"Company:     {company}\n"
                    f"Email:       {email}\n"
                    f"Phone:       {phone or 'Not provided'}\n"
                    f"Interests:   {interests_str}\n"
                    f"{'─'*40}\n\n"
                    f"{message}\n"
                )
                slack_text = (
                    f"💼 *New Sales Enquiry*\n"
                    f"*Name:* {name} — {company}\n"
                    f"*Email:* {email}\n"
                    f"*Interests:* {interests_str}\n"
                    f"*Message:* {message[:400]}"
                )

                notify_errors = []
                err = _send_email(sales_email, f"Sales Enquiry – {name} ({company})", email_body)
                if err:
                    notify_errors.append(f"Email: {err}")
                err = _send_slack("CTK_SLACK_SALES_WEBHOOK", slack_text)
                if err:
                    notify_errors.append(f"Slack: {err}")

                st.success(
                    f"Thanks **{name}**! A member of our sales team will reach out to **{email}** within one business day.",
                    icon="💼",
                )
                if notify_errors:
                    st.warning("Message recorded, but some notifications failed: " + " | ".join(notify_errors))

    with col_info:
        st.markdown(
            """
            <div class="ctk-support-card">
                <div class="ctk-support-card-title">📞 Direct Contact</div>
                <div class="ctk-info-row">
                    <span class="ctk-info-label">Email</span>
                    <span class="ctk-info-value"><a href="mailto:sales@contractortoolkit.io">sales@contractortoolkit.io</a></span>
                </div>
                <div class="ctk-info-row">
                    <span class="ctk-info-label">Phone</span>
                    <span class="ctk-info-value">+1 (800) 555-0199</span>
                </div>
                <div class="ctk-info-row">
                    <span class="ctk-info-label">Hours</span>
                    <span class="ctk-info-value">Mon–Fri, 8 am – 6 pm PST</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            """
            <div class="ctk-support-card">
                <div class="ctk-support-card-title">🏷️ Plans at a Glance</div>
                <div class="ctk-info-row">
                    <span class="ctk-info-label">Starter</span>
                    <span class="ctk-info-value">1 user &nbsp;<span class="ctk-badge ctk-badge-green">Free</span></span>
                </div>
                <div class="ctk-info-row">
                    <span class="ctk-info-label">Pro</span>
                    <span class="ctk-info-value">Up to 10 users &nbsp;<span class="ctk-badge ctk-badge-orange">Paid</span></span>
                </div>
                <div class="ctk-info-row">
                    <span class="ctk-info-label">Enterprise</span>
                    <span class="ctk-info-value">Unlimited &nbsp;<span class="ctk-badge ctk-badge-red">Custom</span></span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ═══════════════════════════════════════════════════════════════════════════
# 3 · HELP CENTER
# ═══════════════════════════════════════════════════════════════════════════
elif section == "📚 Help Center":
    st.title("📚 Help Center")
    st.caption("Guides, FAQs, and tips for getting the most out of Contractor Tool Kit.")

    search = st.text_input("🔍 Search articles", placeholder="e.g. export PDF, rename files…")

    FAQ = {
        "Getting Started": [
            ("How do I log in?",
             "Use the username and password provided by your administrator. If you've forgotten your credentials, contact support via the Submit a Ticket tab."),
            ("How do I switch between tools?",
             "Click **← Back to Tool Kit** at the top of any tool to return to the home screen, then select a different tool from the card grid."),
            ("Can I run the app offline?",
             "The app requires a network connection to the server. Contact Sales for an enterprise on-premise deployment option."),
        ],
        "Documents & PDFs": [
            ("Why does my PDF look different after signing?",
             "PDF Sign uses incremental updates to preserve the original content. Some viewers may render incremental PDFs slightly differently — try Adobe Acrobat for the most accurate preview."),
            ("What file size is supported for PDF uploads?",
             "Files up to 50 MB are supported. For larger files, compress with a tool like Smallpdf before uploading."),
            ("Can I use my own Word template?",
             "Yes — upload any `.docx` file in Word Template Generator and map your custom placeholders to the form fields."),
        ],
        "Media Tools": [
            ("What is the Camera Renamer naming scheme?",
             "Files are sorted by date taken (EXIF/metadata) and renamed as `01.mp4`, `01_INSTALL.jpg`, `01A.jpg`, `01B.jpg`, `02.mp4`, …  You can also sort by upload order using the toggle on the page."),
            ("What video formats are supported?",
             "`.mov`, `.mp4`, `.avi`, `.mkv`, `.wmv`, `.flv`, `.mpeg`, `.mpg`. Other formats are skipped."),
        ],
        "Account & Billing": [
            ("How do I reset my password?",
             "Ask your admin to update the `STREAMLIT_AUTH_USERS_JSON` environment variable with a new bcrypt-hashed password."),
            ("How do I add a new user?",
             "Add an entry to `STREAMLIT_AUTH_USERS_JSON` with a `username`, `name`, `password` (bcrypt hash), and optional `roles` array."),
        ],
    }

    st.divider()

    query = search.strip().lower()
    found_any = False

    for category, items in FAQ.items():
        filtered = items if not query else [
            (q, a) for q, a in items
            if query in q.lower() or query in a.lower()
        ]
        if not filtered:
            continue
        found_any = True
        st.markdown(f'<div class="ctk-section">{category}</div>', unsafe_allow_html=True)
        for question, answer in filtered:
            with st.expander(question):
                st.markdown(answer)

    if not found_any:
        st.info("No articles matched your search. Try different keywords or submit a support ticket.")

    st.divider()
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown(
            """
            <div class="ctk-support-card" style="text-align:center;">
                <div style="font-size:2rem;">🎫</div>
                <div class="ctk-support-card-title" style="text-align:center;">Still stuck?</div>
                <p style="font-size:0.83rem;color:#555;">Open a support ticket and our team will help.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Submit a Ticket", use_container_width=True, key="_hc_ticket"):
            st.session_state["_contact_nav"] = "🎫 Submit a Ticket"
            st.rerun()
    with col_b:
        st.markdown(
            """
            <div class="ctk-support-card" style="text-align:center;">
                <div style="font-size:2rem;">💼</div>
                <div class="ctk-support-card-title" style="text-align:center;">Need a demo?</div>
                <p style="font-size:0.83rem;color:#555;">Talk to sales about your team's requirements.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Contact Sales", use_container_width=True, key="_hc_sales"):
            st.session_state["_contact_nav"] = "💼 Contact Sales"
            st.rerun()
    with col_c:
        st.markdown(
            """
            <div class="ctk-support-card" style="text-align:center;">
                <div style="font-size:2rem;">📧</div>
                <div class="ctk-support-card-title" style="text-align:center;">Email us directly</div>
                <p style="font-size:0.83rem;color:#555;"><a href="mailto:support@contractortoolkit.io" style="color:#E87722;">support@contractortoolkit.io</a></p>
            </div>
            """,
            unsafe_allow_html=True,
        )
