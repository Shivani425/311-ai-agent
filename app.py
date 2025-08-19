# app.py — 311 AI Agent with robust address verification (OSM + optional Google fallback)
import os, re, random, csv, io, time, requests
from datetime import datetime
import streamlit as st

# =============================
# Utilities
# =============================

def make_ticket(prefix="CTY"):
    return f"{prefix}-{datetime.now().strftime('%y%m%d')}-{random.randint(1000,9999)}"

def normalize(txt: str) -> str:
    return re.sub(r"\s+", " ", txt.strip().lower())

# Expand common street abbreviations to help OSM match
_ABBR = {
    r"\bln\b": "lane",
    r"\brd\b": "road",
    r"\bst\b": "street",
    r"\bdr\b": "drive",
    r"\bave\b": "avenue",
    r"\bblvd\b": "boulevard",
    r"\bct\b": "court",
    r"\bpl\b": "place",
    r"\bpkwy\b": "parkway",
    r"\bhwy\b": "highway",
}
def normalize_address_for_geocoder(addr: str) -> str:
    a = " " + addr.strip().lower() + " "
    for pat, rep in _ABBR.items():
        a = re.sub(pat, rep, a)
    return a.strip()

def contains_any(text, keywords):
    t = normalize(text)
    return any(k in t for k in keywords)

# =============================
# Geocoding (OSM first, Google fallback)
# =============================

def geocode_osm(address: str, city=None, state=None):
    """
    Geocode with OpenStreetMap/Nominatim (no key). Returns dict or None.
    """
    try:
        base = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": address if not city else f"{address}, {city}, {state or ''}",
            "format": "json",
            "addressdetails": 1,
            "limit": 1,
        }
        headers = {"User-Agent": "NC311-Demo/1.0 (streamlit)"}
        r = requests.get(base, params=params, headers=headers, timeout=12)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        top = data[0]
        return {
            "formatted": top.get("display_name"),
            "lat": float(top["lat"]),
            "lng": float(top["lon"]),
            "raw": top,
            "provider": "osm",
        }
    except Exception:
        return None

def geocode_google(address: str, city=None, state=None):
    """
    Geocode with Google Maps (needs GOOGLE_MAPS_API_KEY). Returns dict or None.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        q = address if not city else f"{address}, {city}, {state or ''}"
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        r = requests.get(url, params={"address": q, "key": api_key}, timeout=12)
        r.raise_for_status()
        resp = r.json()
        if resp.get("status") != "OK":
            return None
        top = resp["results"][0]
        loc = top["geometry"]["location"]
        return {
            "formatted": top.get("formatted_address"),
            "lat": float(loc["lat"]),
            "lng": float(loc["lng"]),
            "raw": top,
            "provider": "google",
        }
    except Exception:
        return None

def verify_address(address: str, city=None, state=None):
    """
    Normalize & try OSM then Google. Returns dict or None.
    """
    if not address:
        return None
    a = normalize_address_for_geocoder(address)
    # Try OSM
    hit = geocode_osm(a, city, state)
    if hit:
        return hit
    # Fallback Google
    hit = geocode_google(a, city, state)
    if hit:
        return hit
    return None

# =============================
# City profile (demo)
# =============================

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
                "link": "https://www.townofcary.org/"  # example link for NC demo
            },
        },
        "faq": [
            ("Emergencies", "Call 911. For non-emergencies, use your local non-emergency line."),
            ("Town Hall hours", "Mon–Fri, typical business hours (see city website)."),
            ("Bulk pickup", "Usually by scheduled request; check your sanitation portal."),
        ],
    }

# =============================
# Intents / slot filling
# =============================

INTENT_PATTERNS = [
    ("pothole", ["pothole", "road hole", "asphalt", "road damage", "street crack"]),
    ("trash_schedule", ["trash", "garbage", "recycle", "pickup", "collection", "bin"]),
    ("noise_complaint", ["noise", "loud", "party", "music", "construction noise"]),
    ("streetlight", ["streetlight", "light out", "lamp", "street light"]),
    ("stray_animal", ["stray", "dog", "cat", "animal control", "lost pet"]),
    ("general_info", ["info", "information", "hours", "phone", "contact", "permit", "parks", "general"]),
]

REQUIRED_FIELDS = {
    "pothole": ["street_address", "description"],
    "trash_schedule": ["street_address"],
    "noise_complaint": ["incident_time", "location", "description"],
    "streetlight": ["nearest_address", "description"],
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
    if t in ["help", "menu", "hi", "hello", "start", "show menu"]:
        return "menu"
    for intent, keys in INTENT_PATTERNS:
        if contains_any(t, keys):
            return intent
    return "unknown"

# =============================
# Streamlit state
# =============================

st.set_page_config(page_title="311 AI Agent — Streamlit", page_icon="🧰", layout="wide")

if "city_cfg" not in st.session_state:
    st.session_state.city_cfg = make_city_profile("Morrisville", "North Carolina")
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

# =============================
# Helpers
# =============================

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

# Core dispatcher
def push_user_and_process(text: str):
    st.session_state.messages.append({"role": "user", "content": text})
    # If we are collecting fields, treat the input as the next field value
    if st.session_state.active_intent and st.session_state.pending_fields:
        field = st.session_state.pending_fields[0]
        val = text.strip()

        # Allow skip for optional fields
        if normalize(val) == "skip" and field.endswith("_optional"):
            st.session_state.filled_fields[field] = None
        else:
            st.session_state.filled_fields[field] = val

            # If this field is an address field, try to verify it immediately
            if field in ("street_address", "nearest_address", "location"):
                meta = st.session_state.city_cfg["meta"]
                verified = verify_address(val, meta["city"], meta["state"])
                if verified:
                    st.session_state.filled_fields["address_verified"] = verified
                    st.session_state.messages.append({
                        "role":"assistant",
                        "content": f"📍 Verified: **{verified['formatted']}**  "
                                   f"(_provider: {verified['provider']}, "
                                   f"lat: {verified['lat']:.6f}, lon: {verified['lng']:.6f}_)"
                    })
                else:
                    st.session_state.messages.append({
                        "role":"assistant",
                        "content": "⚠️ I couldn’t verify that address. I’ll continue, but you can re-enter it or use the Address Helper."
                    })

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

    # Fresh intent
    intent = detect_intent(text)
    if intent == "menu":
        st.session_state.messages.append({"role": "assistant", "content": show_menu()})

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
            "I’m not sure I understood. Type `menu` to see options, or say 'Report a pothole' or 'Trash pickup day'."})

# =============================
# UI Layout
# =============================

st.title("🧰 311 AI Agent — Streamlit App")

# Sidebar: city & address helper
with st.sidebar:
    st.markdown("## 311 AI Agent")
    meta = st.session_state.city_cfg["meta"]
    st.markdown(f"**City Profile:** {meta['city']}, {meta['state']}")

    st.markdown("### City")
    city = st.text_input("City", value=meta["city"])
    state = st.text_input("State", value=meta["state"])
    if st.button("Apply city"):
        st.session_state.city_cfg = make_city_profile(city.strip() or meta["city"], state.strip() or meta["state"])
        st.success("City profile updated.")
        st.rerun()

    st.markdown("### Address Helper (optional)")
    provider = st.selectbox("Provider", ["OpenStreetMap (No key)", "Google (needs key)"], index=0)
    addr_q = st.text_input("Search or paste an address")
    if st.button("Find address"):
        v = None
        if provider.startswith("OpenStreetMap"):
            v = geocode_osm(addr_q, city, state)
        else:
            v = geocode_google(addr_q, city, state)
        if v:
            st.session_state["last_lookup_candidates"] = [v]
        else:
            st.session_state["last_lookup_candidates"] = []

    picks = st.session_state.get("last_lookup_candidates", [])
    chosen_idx = st.radio("Pick one", list(range(len(picks))), format_func=lambda i: picks[i]["formatted"]) if picks else None
    if st.button("Use this address", disabled=(not picks)):
        if chosen_idx is not None:
            st.session_state.filled_fields["address_verified"] = picks[chosen_idx]
            st.success("Address stored. Continue your request in the chat.")

    st.divider()
    if st.button("🔄 Reset conversation"):
        st.session_state.messages = []
        st.session_state.active_intent = None
        st.session_state.pending_fields = []
        st.session_state.filled_fields = {}
        st.rerun()

# Conversation history
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# Initial greeting
if not any(m["role"] == "assistant" for m in st.session_state.messages):
    txt = "Hi! I’m your 311 assistant. Type `menu` to see services or ask directly (e.g., `report a pothole`)."
    st.session_state.messages.append({"role":"assistant","content":txt})
    with st.chat_message("assistant"):
        st.markdown(txt)

# Input
user_input = st.chat_input("Type here…")
if user_input:
    push_user_and_process(user_input)

# Export tickets
st.divider()
if st.session_state.ticket_log:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["ticket_id","service","city","state","payload","created_at"])
    writer.writeheader()
    for r in st.session_state.ticket_log:
        writer.writerow(r)
    st.download_button("⬇️ Download tickets.csv", out.getvalue(), file_name="tickets.csv", mime="text/csv")
