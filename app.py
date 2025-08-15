# app.py — 311 AI Agent (Streamlit) with City+State sidebar selector
import re, random, csv, io
from datetime import datetime
import streamlit as st

# ---------- Utilities ----------
def make_ticket(prefix="CTY"):
    return f"{prefix}-{datetime.now().strftime('%y%m%d')}-{random.randint(1000,9999)}"

def normalize(txt: str) -> str:
    return re.sub(r"\s+", " ", txt.strip().lower())

def contains_any(text, keywords):
    t = normalize(text)
    return any(k in t for k in keywords)

# ---------- States list for sidebar ----------
US_STATES = [
    "Your State", "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois",
    "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
    "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana",
    "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
    "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah",
    "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming"
]

# ---------- City profile ----------
def make_city_profile(city="Your City", state="Your State"):
    return {
        "meta": {"city": city, "state": state},
        "services": {
            "pothole": {
                "description": "Report a pothole or road surface issue",
                "fields": ["street_address", "nearest_intersection", "description", "photo_url_optional"],
                "link": "https://example.org/forms/pothole",
                "sla_days": 5,
            },
            "trash_schedule": {
                "description": "Find trash & recycling pickup day",
                "fields": ["street_address", "zip_optional"],
                "link": "https://example.org/trash-schedule",
            },
            "noise_complaint": {
                "description": "Report excessive noise",
                "fields": ["incident_time", "location", "description"],
                "link": "https://example.org/forms/noise",
            },
            "streetlight": {
                "description": "Report a streetlight outage",
                "fields": ["pole_number_optional", "nearest_address", "description"],
                "link": "https://example.org/forms/streetlight",
                "sla_days": 7,
            },
            "stray_animal": {
                "description": "Report a stray or lost animal",
                "fields": ["location", "animal_type", "description"],
                "link": "https://example.org/forms/animal",
            },
            "general_info": {
                "description": "Hours, phone numbers, permits, parks, and other info",
                "fields": [],
                "link": "https://example.org/city-info",
            },
        },
        "faq": [
            ("Emergencies", "Call 911. For non-emergencies, use your local non-emergency line."),
            ("Town Hall hours", "Mon–Fri, typical business hours (see city website)."),
            ("Bulk pickup", "Usually by scheduled request; check your sanitation portal."),
        ],
    }

# ---------- NLU / intents (simple rules) ----------
INTENT_PATTERNS = [
    ("pothole", ["pothole", "road hole", "asphalt", "road damage", "street crack"]),
    ("trash_schedule", ["trash", "garbage", "recycle", "pickup", "collection", "bin"]),
    ("noise_complaint", ["noise", "loud", "party", "music", "construction noise"]),
    ("streetlight", ["streetlight", "light out", "lamp", "street light"]),
    ("stray_animal", ["stray", "dog", "cat", "animal control", "lost pet"]),
    ("general_info", ["info", "information", "hours", "phone", "contact", "permit", "parks"]),
]

REQUIRED_FIELDS = {
    "pothole": ["street_address", "description"],
    "trash_schedule": ["street_address"],
    "noise_complaint": ["incident_time", "location", "description"],
    "streetlight": ["nearest_address"],
    "stray_animal": ["location", "animal_type"],
}

FIELD_QUESTIONS = {
    "street_address": "What is the street address?",
    "nearest_intersection": "What is the nearest intersection?",
    "description": "Please describe the issue briefly.",
    "photo_url_optional": "If you have a photo URL, share it (or say 'skip').",
    "zip_optional": "What is the ZIP code? (or say 'skip')",
    "incident_time": "When did this happen? (date & time)",
    "location": "Where did this occur? (address, landmark or intersection)",
    "pole_number_optional": "If you see a pole number, share it (or say 'skip').",
    "nearest_address": "What is the nearest address to the light?",
    "animal_type": "What kind of animal is it?",
}

def detect_intent(text: str):
    t = normalize(text)
    if "yes please adapt this to my city's open data and services categories" in t:
        return "adapt_city"
    for intent, keys in INTENT_PATTERNS:
        if contains_any(t, keys):
            return intent
    if t in ["help", "menu", "hi", "hello", "start"]:
        return "menu"
    return "unknown"

# ---------- App state ----------
st.set_page_config(page_title="311 AI Agent — Streamlit", page_icon="🧰", layout="wide")

if "city_cfg" not in st.session_state:
    st.session_state.city_cfg = make_city_profile()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "active_intent" not in st.session_state:
    st.session_state.active_intent = None
if "pending_fields" not in st.session_state:
    st.session_state.pending_fields = []
if "filled_fields" not in st.session_state:
    st.session_state.filled_fields = {}
if "ticket_log" not in st.session_state:
    st.session_state.ticket_log = []  # list of dicts

# ---------- Helpers ----------
def show_menu():
    svcs = st.session_state.city_cfg["services"]
    bullets = "\n".join([f"- **{k}** — {v['description']}" for k, v in svcs.items()])
    return (
        "I can help with:\n"
        f"{bullets}\n\n"
        "Try: 'Report a pothole', 'Trash pickup day', 'Noise complaint', "
        "'Streetlight out', 'Stray dog', or 'General info'."
    )

def next_slot_question():
    if not st.session_state.active_intent:
        return None
    req = REQUIRED_FIELDS.get(st.session_state.active_intent, [])
    svc_fields = st.session_state.city_cfg["services"].get(st.session_state.active_intent, {}).get("fields", [])
    ordered = [f for f in req if f not in st.session_state.filled_fields] + \
              [f for f in svc_fields if f not in req and f not in st.session_state.filled_fields]
    st.session_state.pending_fields = ordered
    if ordered:
        return FIELD_QUESTIONS.get(ordered[0], f"Provide {ordered[0]}:")
    return None

def finalize_case():
    intent = st.session_state.active_intent
    cfg = st.session_state.city_cfg
    meta = cfg["meta"]
    svc = cfg["services"][intent]
    ticket_id = make_ticket(prefix=(meta["city"][:2] or "CT").upper())
    payload = {k: v for k, v in st.session_state.filled_fields.items()}
    st.session_state.ticket_log.append({
        "ticket_id": ticket_id,
        "service": intent,
        "city": meta["city"],
        "state": meta["state"],
        "payload": payload,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    msg = (
        f"✅ **Submitted** your *{intent.replace('_',' ')}* request.\n\n"
        f"- Ticket ID: **{ticket_id}**\n"
        f"- City: **{meta['city']}, {meta['state']}**\n"
        f"- Intake fields: `{payload}`\n"
        f"- Reference: {svc.get('link','(no link)')}\n"
    )
    if "sla_days" in svc:
        msg += f"- Estimated resolution target: **~{svc['sla_days']} business days**\n"
    msg += "\nAnything else I can do? Type `menu` to see options."
    return msg

def push_user_and_process(text: str):
    """Simulate a user message and produce assistant response (used by Guide buttons)."""
    st.session_state.messages.append({"role": "user", "content": text})

    # If mid slot-filling, treat as field value
    if st.session_state.active_intent and st.session_state.pending_fields:
        field = st.session_state.pending_fields[0]
        val = text.strip()
        if normalize(val) == "skip" and field.endswith("_optional"):
            st.session_state.filled_fields[field] = None
        else:
            st.session_state.filled_fields[field] = val
        nxt = next_slot_question()
        if nxt:
            st.session_state.messages.append({"role": "assistant", "content": nxt})
        else:
            reply = finalize_case()
            st.session_state.active_intent = None
            st.session_state.pending_fields = []
            st.session_state.filled_fields = {}
            st.session_state.messages.append({"role": "assistant", "content": reply})
        return

    # Detect a fresh intent
    intent = detect_intent(text)
    if intent == "menu":
        st.session_state.messages.append({"role": "assistant", "content": show_menu()})
    elif intent == "adapt_city":
        t = normalize(text)
        city, state = "Your City", "Your State"
        if "name is" in t and "in the state" in t:
            try:
                city = t.split("name is", 1)[1].split("in the state", 1)[0].strip(" .,:;").title()
                state = t.split("in the state", 1)[1].strip(" .,:;").title()
            except Exception:
                pass
        st.session_state.city_cfg = make_city_profile(city, state)
        st.session_state.messages.append({"role": "assistant", "content": f"👍 Adapted to **{city}, {state}**. Type `menu` to see services."})
    elif intent in st.session_state.city_cfg["services"]:
        st.session_state.active_intent = intent
        st.session_state.filled_fields = {}
        nxt = next_slot_question()
        if not nxt:
            svc = st.session_state.city_cfg["services"][intent]
            reply = (
                f"**{intent.replace('_',' ').title()}** — {svc['description']}\n\n"
                f"More info: {svc.get('link','(no link)')}\n\nType `menu` for other options."
            )
            st.session_state.active_intent = None
            st.session_state.pending_fields = []
            st.session_state.filled_fields = {}
            st.session_state.messages.append({"role": "assistant", "content": reply})
        else:
            preface = f"Okay, let's file a **{intent.replace('_',' ')}** request.\n"
            st.session_state.messages.append({"role": "assistant", "content": preface + "\n" + nxt})
    else:
        st.session_state.messages.append({"role": "assistant", "content":
            "I’m not sure I understood. Type `menu` to see options, "
            "or say 'Report a pothole' or 'Trash pickup day'."})

# ---------- Sidebar (with City+State selector) ----------
with st.sidebar:
    st.markdown("## 311 AI Agent")

    # Current profile
    meta = st.session_state.city_cfg["meta"]
    st.markdown(f"**City Profile:** {meta['city']}, {meta['state']}")

    # Quick adapt UI
    st.markdown("#### Adapt city & state")
    city_default = meta.get("city", "Your City")
    state_default = meta.get("state", "Your State")
    city_input = st.text_input("City", value=city_default, placeholder="e.g., Austin")

    try:
        state_index = US_STATES.index(state_default) if state_default in US_STATES else 0
    except Exception:
        state_index = 0
    state_input = st.selectbox("State", US_STATES, index=state_index)

    if st.button("Apply profile"):
        st.session_state.city_cfg = make_city_profile(city_input.strip() or "Your City",
                                                      state_input.strip() or "Your State")
        st.success(f"Adapted to {city_input or 'Your City'}, {state_input or 'Your State'}")

    st.caption(
        "Or use the chat phrase:\n\n"
        "“yes please adapt this to my city's Open data and services categories. "
        "My city's name is <City> in the state <State>.”"
    )

    # Recent tickets
    if st.session_state.ticket_log:
        st.divider()
        st.markdown("**Recent Tickets**")
        for t in st.session_state.ticket_log[-5:][::-1]:
            st.write(f"• {t['ticket_id']} — {t['service']}")

    # Optional: quick reset for demos
    st.divider()
    if st.button("🔄 Reset conversation"):
        st.session_state.messages = []
        st.session_state.active_intent = None
        st.session_state.pending_fields = []
        st.session_state.filled_fields = {}
        st.experimental_rerun()

# ---------- Main Layout ----------
st.title("🧰 311 AI Agent — Streamlit App")
tab_guide, tab_live = st.tabs(["🧭 Guide Mode", "💬 Live Agent"])

# ---- Guide Mode (click-through demo) ----
with tab_guide:
    st.markdown("Use these buttons to run a demo without typing.")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("1) Show menu"):
            push_user_and_process("menu")
    with c2:
        if st.button("2) Start pothole report"):
            push_user_and_process("Report a pothole")
    with c3:
        if st.button("3) Give address"):
            push_user_and_process("123 Main St")
    with c4:
        if st.button("4) Describe issue"):
            push_user_and_process("Large hole near the curb; dangerous for bikes")

    c5, c6, c7, c8 = st.columns(4)
    with c5:
        if st.button("5) Trash schedule"):
            push_user_and_process("Trash pickup day")
    with c6:
        if st.button("6) Provide address (trash)"):
            push_user_and_process("456 Oak Ave")
    with c7:
        if st.button("7) Adapt to a city"):
            push_user_and_process(
                "yes please adapt this to my city's Open data and services categories. "
                "My city's name is Springfield in the state Illinois."
            )
    with c8:
        if st.button("8) Show menu after adapt"):
            push_user_and_process("menu")

    st.divider()
    st.markdown("#### Conversation")
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

# ---- Live Agent (type messages) ----
with tab_live:
    # history
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    if not any(m["role"] == "assistant" for m in st.session_state.messages):
        st.session_state.messages.append({"role":"assistant","content":"Hi! I’m your 311 assistant. Type `menu` to see what I can do."})
        with st.chat_message("assistant"):
            st.markdown("Hi! I’m your 311 assistant. Type `menu` to see what I can do.")

    user_input = st.chat_input("Type here…")
    if user_input:
        push_user_and_process(user_input)

# ---- Export tickets ----
st.divider()
if st.session_state.ticket_log:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["ticket_id","service","city","state","payload","created_at"])
    writer.writeheader()
    for r in st.session_state.ticket_log:
        writer.writerow(r)
    st.download_button("⬇️ Download tickets.csv", out.getvalue(), file_name="tickets.csv", mime="text/csv")
