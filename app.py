# app.py — 311 AI Agent (Streamlit, Live-Agent only)
import re, random, csv, io
from datetime import datetime
import streamlit as st

# ---------- page chrome ----------
st.set_page_config(page_title="311 AI Agent", page_icon="🧰", layout="wide")
st.markdown("""
<style>
.main .block-container{max-width:860px;}
.bubble{border-radius:16px; padding:12px 14px; margin:8px 0; max-width:85%; line-height:1.35;}
.left{background:#0c3a5b; color:#fff; border-top-left-radius:6px;}
.right{background:#f1f5f9; color:#111; margin-left:auto; border-top-right-radius:6px;}
.stChatInputContainer{position:sticky; bottom:0; background:linear-gradient(180deg,rgba(255,255,255,0),#fff 30%);}
</style>
""", unsafe_allow_html=True)

def bubble_left(t:str):  st.markdown(f'<div class="bubble left">{t}</div>', unsafe_allow_html=True)
def bubble_right(t:str): st.markdown(f'<div class="bubble right">{t}</div>', unsafe_allow_html=True)

# ---------- utils ----------
def make_ticket(prefix="CTY"):
    return f"{prefix}-{datetime.now().strftime('%y%m%d')}-{random.randint(1000,9999)}"
def normalize(txt:str)->str: return re.sub(r"\s+", " ", txt.strip().lower())
def contains_any(text, keys): return any(k in normalize(text) for k in keys)

# ---------- simple state list ----------
US_STATES = ["Alabama","Alaska","Arizona","Arkansas","California","Colorado","Connecticut","Delaware",
"District of Columbia","Florida","Georgia","Hawaii","Idaho","Illinois","Indiana","Iowa","Kansas","Kentucky",
"Louisiana","Maine","Maryland","Massachusetts","Michigan","Minnesota","Mississippi","Missouri","Montana",
"Nebraska","Nevada","New Hampshire","New Jersey","New Mexico","New York","North Carolina","North Dakota",
"Ohio","Oklahoma","Oregon","Pennsylvania","Rhode Island","South Carolina","South Dakota","Tennessee","Texas",
"Utah","Vermont","Virginia","Washington","West Virginia","Wisconsin","Wyoming"]

# ---------- catalog ----------
def make_city_profile(city="Morrisville", state="North Carolina"):
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
                "fields": ["nearest_address", "pole_number_optional", "description"],
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
    }

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

def detect_intent(text:str):
    t = normalize(text)
    if "yes please adapt this to my city's open data and services categories" in t: return "adapt_city"
    for intent, keys in INTENT_PATTERNS:
        if contains_any(t, keys): return intent
    if t in ["help","menu","hi","hello","start"]: return "menu"
    return "unknown"

# ---------- session ----------
if "city_cfg"   not in st.session_state: st.session_state.city_cfg = make_city_profile()
if "messages"   not in st.session_state: st.session_state.messages = []
if "active_intent" not in st.session_state: st.session_state.active_intent = None
if "pending_fields" not in st.session_state: st.session_state.pending_fields = []
if "filled_fields"  not in st.session_state: st.session_state.filled_fields = {}
if "ticket_log"     not in st.session_state: st.session_state.ticket_log = []

# ---------- helpers ----------
def show_menu():
    svcs = st.session_state.city_cfg["services"]
    bullets = "\n".join([f"- **{k}** — {v['description']}" for k,v in svcs.items()])
    return "I can help with:\n" + bullets + "\n\nTry: 'Report a pothole', 'Trash pickup day', 'Streetlight out', 'Stray dog', or 'General info'."

def next_slot_question():
    if not st.session_state.active_intent: return None
    req = REQUIRED_FIELDS.get(st.session_state.active_intent, [])
    svc_fields = st.session_state.city_cfg["services"][st.session_state.active_intent]["fields"]
    ordered = [f for f in req if f not in st.session_state.filled_fields] + \
              [f for f in svc_fields if f not in req and f not in st.session_state.filled_fields]
    st.session_state.pending_fields = ordered
    return FIELD_QUESTIONS.get(ordered[0], f"Provide {ordered[0]}:") if ordered else None

def finalize_case():
    intent = st.session_state.active_intent
    meta = st.session_state.city_cfg["meta"]
    svc  = st.session_state.city_cfg["services"][intent]
    ticket_id = make_ticket(prefix=(meta["city"][:2] or "CT").upper())
    payload = dict(st.session_state.filled_fields)
    st.session_state.ticket_log.append({
        "ticket_id": ticket_id, "service": intent, "city": meta["city"], "state": meta["state"],
        "payload": payload, "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    msg = (f"✅ **Submitted** your *{intent.replace('_',' ')}* request.\n\n"
           f"- Ticket ID: **{ticket_id}**\n- City: **{meta['city']}, {meta['state']}**\n"
           f"- Intake fields: `{payload}`\n- Reference: {svc.get('link','(no link)')}\n")
    if "sla_days" in svc: msg += f"- Estimated resolution target: **~{svc['sla_days']} business days**\n"
    return msg + "\nAnything else I can do? Type `menu`."

# ---------- single dispatcher (commands take priority even mid-form) ----------
def push_user_and_process(text:str):
    st.session_state.messages.append({"role":"user","content":text})
    tnorm = normalize(text)
    intent_guess = detect_intent(text)

    # mid-form: if user typed a command, cancel and restart
    if st.session_state.active_intent and st.session_state.pending_fields:
        if intent_guess in st.session_state.city_cfg["services"] or intent_guess in {"menu","adapt_city"}:
            st.session_state.active_intent = None
            st.session_state.pending_fields = []
            st.session_state.filled_fields = {}
            return push_user_and_process(text)

        # treat as answer
        field = st.session_state.pending_fields[0]
        val = text.strip()
        if tnorm == "skip" and field.endswith("_optional"):
            st.session_state.filled_fields[field] = None
        else:
            st.session_state.filled_fields[field] = val

        nxt = next_slot_question()
        if nxt:
            st.session_state.messages.append({"role":"assistant","content":nxt})
        else:
            msg = finalize_case()
            st.session_state.active_intent = st.session_state.pending_fields = []
            st.session_state.filled_fields = {}
            st.session_state.messages.append({"role":"assistant","content":msg})
        return

    # not mid-form: handle commands
    if intent_guess == "menu":
        st.session_state.messages.append({"role":"assistant","content":show_menu()}); return

    if intent_guess == "adapt_city":
        t = tnorm
        city, state = "Your City", "Your State"
        if "name is" in t and "in the state" in t:
            try:
                city = t.split("name is",1)[1].split("in the state",1)[0].strip(" .,:;").title()
                state = t.split("in the state",1)[1].strip(" .,:;").title()
            except: pass
        st.session_state.city_cfg = make_city_profile(city, state)
        st.session_state.messages.append({"role":"assistant","content":f"👍 Adapted to **{city}, {state}**. Type `menu`."})
        return

    if intent_guess in st.session_state.city_cfg["services"]:
        st.session_state.active_intent = intent_guess
        st.session_state.filled_fields = {}
        nxt = next_slot_question()
        if nxt:
            st.session_state.messages.append({"role":"assistant","content":f"Okay, let's file a **{intent_guess.replace('_',' ')}** request.\n\n{nxt}"})
        else:
            svc = st.session_state.city_cfg["services"][intent_guess]
            st.session_state.messages.append({"role":"assistant","content":
                f"**{intent_guess.replace('_',' ').title()}** — {svc['description']}\n\nMore info: {svc.get('link','(no link)')}"})
        return

    st.session_state.messages.append({"role":"assistant","content":
        "I’m not sure I understood. Type `menu`, or try 'Report a pothole' or 'Trash pickup day'."})

# ---------- sidebar ----------
with st.sidebar:
    st.markdown("## 311 AI Agent")
    meta = st.session_state.city_cfg["meta"]
    st.markdown(f"**City Profile:** {meta['city']}, {meta['state']}")
    idx = US_STATES.index(meta["state"]) if meta["state"] in US_STATES else US_STATES.index("North Carolina")
    new_state = st.selectbox("State", US_STATES, index=idx)
    new_city  = st.text_input("City", value=meta["city"])
    if st.button("Apply profile"):
        st.session_state.city_cfg = make_city_profile(new_city or "Your City", new_state or "Your State")
        st.success(f"Adapted to {new_city or 'Your City'}, {new_state or 'Your State'}")
    if st.session_state.ticket_log:
        st.divider(); st.markdown("**Recent Tickets**")
        for t in st.session_state.ticket_log[-5:][::-1]:
            st.write(f"• {t['ticket_id']} — {t['service']}")
    st.divider()
    if st.button("🔄 Reset conversation"):
        st.session_state.messages = []; st.session_state.active_intent = None
        st.session_state.pending_fields = []; st.session_state.filled_fields = {}
        st.experimental_rerun()

# ---------- main ----------
st.title("🧰 311 AI Agent — Streamlit App")
bubble_left("To protect your personal data, please don’t share sensitive info (like full card details or SSN).")
bubble_left("Hello! I’m your 311 virtual assistant. Type `menu` to see services or ask directly.")

# transcript with bubbles
for m in st.session_state.messages:
    (bubble_right if m["role"]=="user" else bubble_left)(m["content"])

if not any(m["role"]=="assistant" for m in st.session_state.messages):
    first = "Hi! I’m your 311 assistant. Type `menu` for potholes, trash pickup, streetlight, and more."
    st.session_state.messages.append({"role":"assistant","content":first}); bubble_left(first)

user_in = st.chat_input("Type here…")
if user_in:
    bubble_right(user_in)
    push_user_and_process(user_in)

# export
st.divider()
if st.session_state.ticket_log:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["ticket_id","service","city","state","payload","created_at"])
    writer.writeheader()
    for r in st.session_state.ticket_log: writer.writerow(r)
    st.download_button("⬇️ Download tickets.csv", out.getvalue(), file_name="tickets.csv", mime="text/csv")
