import streamlit as st
import os
import io
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Push Streamlit Cloud secrets into os.environ so agent modules can use them
try:
    for _k in ("GEMINI_API_KEY", "APP_USERNAME", "APP_PASSWORD"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = st.secrets[_k]
except Exception:
    pass

from agents.doc_agent import extract_document_fields, extract_prefilled_report
from agents.photo_agent import analyze_photo
from utils.validators import (
    check_missing_items, get_required_docs, get_special_photos,
    cross_check_plumb_twist, cross_check_tension,
)
from utils.docx_builder import build_report, generate_field_observations, OBS_SECTIONS_BY_TOWER
from utils.gallery import (
    sig, sig_cache, uploader_key, bump_uploader, new_uploads,
    render_file_gallery, render_photo_gallery,
)

st.set_page_config(
    page_title="PMI Closeout Report Generator — ATSS",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── SVG Assets ────────────────────────────────────────────────────────────────

_TOWER_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 720" fill="none"
     stroke="white" stroke-linecap="round" stroke-linejoin="round">
  <line x1="150" y1="0"   x2="150" y2="52"  stroke-width="3"/>
  <polyline points="148,52 134,122 117,212 99,302 82,392 64,482 47,572 25,682" stroke-width="2.2"/>
  <polyline points="152,52 166,122 183,212 201,302 218,392 236,482 253,572 275,682" stroke-width="2.2"/>
  <line x1="25"  y1="682" x2="275" y2="682" stroke-width="2.2"/>
  <line x1="134" y1="122" x2="166" y2="122" stroke-width="1.4"/>
  <line x1="117" y1="212" x2="183" y2="212" stroke-width="1.4"/>
  <line x1="99"  y1="302" x2="201" y2="302" stroke-width="1.4"/>
  <line x1="82"  y1="392" x2="218" y2="392" stroke-width="1.4"/>
  <line x1="64"  y1="482" x2="236" y2="482" stroke-width="1.4"/>
  <line x1="47"  y1="572" x2="253" y2="572" stroke-width="1.4"/>
  <line x1="148" y1="52"  x2="166" y2="122" stroke-width="0.9"/>
  <line x1="152" y1="52"  x2="134" y2="122" stroke-width="0.9"/>
  <line x1="134" y1="122" x2="183" y2="212" stroke-width="0.9"/>
  <line x1="166" y1="122" x2="117" y2="212" stroke-width="0.9"/>
  <line x1="117" y1="212" x2="201" y2="302" stroke-width="0.9"/>
  <line x1="183" y1="212" x2="99"  y2="302" stroke-width="0.9"/>
  <line x1="99"  y1="302" x2="218" y2="392" stroke-width="0.9"/>
  <line x1="201" y1="302" x2="82"  y2="392" stroke-width="0.9"/>
  <line x1="82"  y1="392" x2="236" y2="482" stroke-width="0.9"/>
  <line x1="218" y1="392" x2="64"  y2="482" stroke-width="0.9"/>
  <line x1="64"  y1="482" x2="253" y2="572" stroke-width="0.9"/>
  <line x1="236" y1="482" x2="47"  y2="572" stroke-width="0.9"/>
  <line x1="47"  y1="572" x2="275" y2="682" stroke-width="0.9"/>
  <line x1="253" y1="572" x2="25"  y2="682" stroke-width="0.9"/>
  <line x1="25"  y1="682" x2="10"  y2="720" stroke-width="2.5"/>
  <line x1="275" y1="682" x2="290" y2="720" stroke-width="2.5"/>
</svg>"""

_LOGO_ICON = """
<svg width="38" height="38" viewBox="0 0 38 38" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="19" y1="2"  x2="19" y2="10" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="18" y1="10" x2="4"  y2="36" stroke="white" stroke-width="2"   stroke-linecap="round"/>
  <line x1="20" y1="10" x2="34" y2="36" stroke="white" stroke-width="2"   stroke-linecap="round"/>
  <line x1="12" y1="20" x2="26" y2="20" stroke="white" stroke-width="1.4" stroke-linecap="round"/>
  <line x1="7"  y1="30" x2="31" y2="30" stroke="white" stroke-width="1.4" stroke-linecap="round"/>
  <line x1="12" y1="20" x2="26" y2="30" stroke="white" stroke-width="0.9" stroke-linecap="round"/>
  <line x1="26" y1="20" x2="12" y2="30" stroke="white" stroke-width="0.9" stroke-linecap="round"/>
</svg>"""

# ── Auth helpers ──────────────────────────────────────────────────────────────

def _get_credentials():
    """Read credentials from st.secrets (deployment) or env (local)."""
    try:
        username = st.secrets["APP_USERNAME"]
        password = st.secrets["APP_PASSWORD"]
    except Exception:
        username = os.environ.get("APP_USERNAME", "atss_admin")
        password = os.environ.get("APP_PASSWORD", "atss@2025")
    return username, password


def _login_page():
    # Override block-container to be a centered light card; full-bleed tech/tower bg
    st.markdown("""
    <style>
    #MainMenu,footer,[data-testid="stHeader"],[data-testid="stToolbar"],
    [data-testid="stDecoration"]{display:none!important;}

    .stApp,[data-testid="stAppViewContainer"]{
        background:
          radial-gradient(circle at 78% 18%,rgba(59,130,246,0.35) 0%,rgba(59,130,246,0) 42%),
          radial-gradient(circle at 12% 82%,rgba(56,189,248,0.18) 0%,rgba(56,189,248,0) 45%),
          linear-gradient(160deg,#050d1c 0%,#0a1c38 45%,#123163 100%)!important;
    }
    /* Make the content area a centered light card.
       Targets the real container hook for this Streamlit version
       (data-testid, not the old ".main" wrapper class) with enough
       specificity to beat the global CSS block that loads unconditionally
       before the login gate. */
    div[data-testid="stMainBlockContainer"]{
        max-width:420px!important;
        padding:2.2rem 2rem 1.8rem!important;
        background:#eef1f4!important;
        border-radius:14px!important;
        margin:7vh auto 2rem!important;
        box-shadow:0 28px 90px rgba(0,0,0,0.5),0 4px 18px rgba(0,0,0,0.3)!important;
        position:relative!important;
        z-index:1!important;
        border:1px solid rgba(255,255,255,0.6)!important;
    }
    /* Inputs inside the card */
    .stTextInput.stTextInput>div>div>input{
        background:#ffffff!important; border:1.5px solid #d7dce3!important;
        border-radius:7px!important; color:#1e293b!important;
        font-size:0.9rem!important; padding:0.65rem 0.85rem!important;
    }
    .stTextInput.stTextInput>div>div>input:focus{
        border-color:#22406e!important;
        box-shadow:0 0 0 3px rgba(34,64,110,0.14)!important;
    }
    .stTextInput.stTextInput label{
        font-size:0.7rem!important; font-weight:700!important;
        color:#64748b!important; text-transform:uppercase!important;
        letter-spacing:0.5px!important;
    }
    /* Login button */
    .stButton.stButton>button{
        background:#1f3a63!important;
        color:white!important; border:none!important; border-radius:7px!important;
        font-weight:700!important; font-size:0.92rem!important; width:100%!important;
        padding:0.65rem!important;
        box-shadow:0 4px 14px rgba(31,58,99,0.4)!important;
        transition:all 0.2s!important;
    }
    .stButton.stButton>button:hover{
        background:#28477a!important;
        box-shadow:0 6px 20px rgba(31,58,99,0.5)!important;
        transform:translateY(-1px)!important;
    }
    /* Google (secondary) button */
    .stButton.stButton>button[kind="secondary"]{
        background:#ffffff!important; color:#334155!important;
        border:1.5px solid #d7dce3!important; box-shadow:none!important;
        font-weight:600!important;
    }
    .stButton.stButton>button[kind="secondary"]:hover{
        background:#f8fafc!important; border-color:#c3cad4!important;
        transform:none!important;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Full-bleed background: tower silhouettes + circuit/tech accents ────────
    tower_bg = _TOWER_SVG.replace(
        'viewBox="0 0 300 720"',
        'viewBox="0 0 300 720" width="260" height="624"'
    )
    st.markdown(f"""
    <div style="position:fixed;top:0;left:0;width:100vw;height:100vh;pointer-events:none;z-index:0;overflow:hidden;">
      <div style="position:absolute;bottom:-4%;left:3%;opacity:0.16;transform:rotate(-2deg);">{tower_bg}</div>
      <div style="position:absolute;bottom:-4%;right:4%;opacity:0.13;transform:rotate(2deg) scaleX(-1);">{tower_bg}</div>
      <svg style="position:absolute;top:6%;right:10%;opacity:0.25;" width="220" height="220" viewBox="0 0 220 220">
        <circle cx="110" cy="110" r="95" fill="none" stroke="#5aa9ff" stroke-width="1"/>
        <circle cx="110" cy="110" r="65" fill="none" stroke="#5aa9ff" stroke-width="1"/>
        <circle cx="110" cy="110" r="4" fill="#5aa9ff"/>
        <line x1="110" y1="15" x2="110" y2="45" stroke="#5aa9ff" stroke-width="1"/>
        <line x1="110" y1="175" x2="110" y2="205" stroke="#5aa9ff" stroke-width="1"/>
        <line x1="15" y1="110" x2="45" y2="110" stroke="#5aa9ff" stroke-width="1"/>
        <line x1="175" y1="110" x2="205" y2="110" stroke="#5aa9ff" stroke-width="1"/>
      </svg>
      <svg style="position:absolute;top:0;left:0;" width="100%" height="100%" opacity="0.06">
        <pattern id="grid" width="46" height="46" patternUnits="userSpaceOnUse">
          <path d="M 46 0 L 0 0 0 46" fill="none" stroke="#5aa9ff" stroke-width="0.6"/>
        </pattern>
        <rect width="100%" height="100%" fill="url(#grid)"/>
      </svg>
    </div>
    """, unsafe_allow_html=True)

    # ── Card content ──────────────────────────────────────────────────────────

    # Logo header (ATS wordmark, top-left aligned like reference)
    st.markdown("""
    <div style="margin-bottom:1.4rem;">
      <div style="display:flex;align-items:baseline;gap:2px;margin-bottom:1.1rem;">
        <span style="font-size:1.5rem;font-weight:900;color:#0f172a;letter-spacing:-0.5px;
             font-family:'Inter',sans-serif;">ATSS</span>
        <span style="font-size:1.1rem;font-weight:900;color:#a3e635;line-height:1;">&rsquo;</span>
      </div>
      <div style="font-size:1.25rem;font-weight:800;color:#0f172a;letter-spacing:-0.4px;
           font-family:'Inter',sans-serif;">Login to your account</div>
      <div style="font-size:0.84rem;color:#64748b;margin-top:0.15rem;
           font-family:'Inter',sans-serif;">Welcome Back!</div>
    </div>
    """, unsafe_allow_html=True)

    username_input = st.text_input("Username", placeholder="Enter username", key="login_username", label_visibility="collapsed")
    password_input = st.text_input("Password", type="password", placeholder="Enter password", key="login_password", label_visibility="collapsed")

    st.markdown("<div style='height:0.7rem'></div>", unsafe_allow_html=True)

    login_clicked = st.button("Login", type="primary", use_container_width=True, key="login_btn")

    st.markdown("""
    <div style="text-align:center;margin-top:0.85rem;">
      <a href="#" style="font-size:0.78rem;color:#1f3a63;font-weight:600;
         text-decoration:none;font-family:'Inter',sans-serif;">Forgot Password?</a>
    </div>
    <div style="display:flex;align-items:center;gap:0.7rem;margin:1.1rem 0 0.9rem;">
      <div style="flex:1;height:1px;background:#d7dce3;"></div>
      <span style="font-size:0.72rem;color:#94a3b8;font-weight:700;
           font-family:'Inter',sans-serif;">OR</span>
      <div style="flex:1;height:1px;background:#d7dce3;"></div>
    </div>
    """, unsafe_allow_html=True)

    google_clicked = st.button("🔵 Continue with Google", type="secondary", use_container_width=True, key="google_btn")
    if google_clicked:
        st.toast("Google Sign-In isn't configured yet — use your username/password.", icon="ℹ️")

    st.markdown("""
    <div style="text-align:center;margin-top:1.6rem;font-size:0.66rem;color:#94a3b8;
         font-family:'Inter',sans-serif;">
      © 2026 Advanced Tower Structural Solutions LLC
    </div>
    """, unsafe_allow_html=True)

    if login_clicked:
        valid_user, valid_pass = _get_credentials()
        if username_input == valid_user and password_input == valid_pass:
            st.session_state["authenticated"] = True
            st.session_state["auth_user"] = username_input
            st.rerun()
        else:
            st.markdown("""
            <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;
                 padding:0.65rem 0.9rem;margin-top:0.8rem;color:#dc2626;font-size:0.81rem;
                 font-family:'Inter',sans-serif;">
              Incorrect username or password.
            </div>
            """, unsafe_allow_html=True)

# ── Main App CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
html,body,[class*="css"]{font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;}

/* App background */
.stApp { background: #eef2f8 !important; }
div[data-testid="stMainBlockContainer"] {
    padding: 1.5rem 2.2rem 3rem !important;
    max-width: 1080px !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg,#040d1a 0%,#081428 45%,#0d1e40 100%) !important;
    border-right: 1px solid rgba(29,78,216,0.2) !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] div,
[data-testid="stSidebar"] label { color: #c8d9f0 !important; }
[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.08) !important;
    margin: 0.6rem 0 !important;
}

/* ── Buttons ── */
.stButton > button {
    border-radius: 9px !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.87rem !important;
    transition: all 0.2s ease !important;
    letter-spacing: 0.1px !important;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg,#1d4ed8 0%,#2563eb 60%,#3b82f6 100%) !important;
    color: white !important;
    border: none !important;
    box-shadow: 0 3px 14px rgba(29,78,216,0.30),0 1px 3px rgba(0,0,0,0.12) !important;
}
.stButton > button[kind="primary"]:hover {
    box-shadow: 0 6px 22px rgba(29,78,216,0.40),0 2px 6px rgba(0,0,0,0.14) !important;
    transform: translateY(-1px) !important;
}
.stButton > button[kind="secondary"] {
    background: #fff !important;
    border: 1.5px solid #cbd5e1 !important;
    color: #334155 !important;
}
.stButton > button[kind="secondary"]:hover {
    border-color: #94a3b8 !important;
    background: #f8fafc !important;
}

/* ── Inputs ── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stNumberInput > div > div > input {
    border-radius: 9px !important;
    border: 1.5px solid #dde4f0 !important;
    background: #fff !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.9rem !important;
    color: #1e293b !important;
    transition: all 0.18s !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus,
.stNumberInput > div > div > input:focus {
    border-color: #1d4ed8 !important;
    box-shadow: 0 0 0 3px rgba(29,78,216,0.10) !important;
    outline: none !important;
}
.stTextInput label,.stTextArea label,.stNumberInput label,.stSelectbox label {
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    color: #475569 !important;
    letter-spacing: 0.3px !important;
    text-transform: uppercase !important;
}
.stSelectbox > div > div {
    border-radius: 9px !important;
    border: 1.5px solid #dde4f0 !important;
    background: #fff !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: #e1e8f5 !important;
    border-radius: 10px !important;
    padding: 4px !important;
    gap: 3px !important;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 0.83rem !important;
    color: #64748b !important;
    padding: 0.45rem 1rem !important;
}
.stTabs [aria-selected="true"] {
    background: white !important;
    color: #1d4ed8 !important;
    box-shadow: 0 1px 5px rgba(0,0,0,0.10) !important;
}

/* ── File uploader ── */
[data-testid="stFileUploader"] {
    border-radius: 10px !important;
    border: 2px dashed #c4d0e8 !important;
    background: #f8faff !important;
}
[data-testid="stFileUploader"]:hover { border-color: #1d4ed8 !important; }

/* ── Expander ── */
.streamlit-expanderHeader {
    border-radius: 9px !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    background: #f1f5fb !important;
}

/* ── Alert / info boxes ── */
[data-testid="stAlert"] { border-radius: 10px !important; }

/* ── Horizontal progress stepper (shared) ── */
.atss-stepper { display:flex; align-items:center; gap:0; margin-bottom:1.5rem; }
.atss-stepper-item {
    display:flex; flex-direction:column; align-items:center; flex:1; position:relative;
}
.atss-stepper-item:not(:last-child)::after {
    content:''; position:absolute; top:15px; left:calc(50% + 15px);
    width:calc(100% - 30px); height:2px;
    background: linear-gradient(90deg, var(--line-color-from), var(--line-color-to));
}
.atss-step-circle {
    width:30px; height:30px; border-radius:50%;
    display:flex; align-items:center; justify-content:center;
    font-size:0.78rem; font-weight:700; font-family:'Inter',sans-serif;
    z-index:1; position:relative;
}
.atss-step-label {
    font-size:0.62rem; font-weight:600; text-align:center; margin-top:5px;
    font-family:'Inter',sans-serif; letter-spacing:0.3px;
    line-height:1.2; max-width:60px;
}
</style>
""", unsafe_allow_html=True)


# ── Auth gate ─────────────────────────────────────────────────────────────────

if not st.session_state.get("authenticated", False):
    _login_page()
    st.stop()

# ── Session state init ────────────────────────────────────────────────────────

def _init():
    defaults = {
        "step": 1,
        "project_info": {},
        "modifications": [],
        "photos": {},
        "special_photos": {},
        "extra_photos": [],  # [{"name": str, "photos": [(bytes, caption, mime, filename, flag), ...]}, ...]
        "documents": {},
        "extra_documents": [],  # [{"name": str, "files": [(bytes, filename, mime), ...]}, ...]
        "deficiencies": "",
        "no_deficiencies": True,
        "num_guys": 3,
        "photo_captions": {},
        "field_observations": {},
        "obs_generated": False,
        "obs_gen_error": None,
        "_doc_extractions": {},  # {(doc_key, sig): extracted_dict} — AI extraction results, shown in gallery previews
        "_as_built_imported": set(),  # doc-extraction keys already imported into modifications
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

TOWER_TYPES = ["Self Support", "Guyed", "Monopole"]

MIME_MAP = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Purpose key for each guyed special photo section
GUYED_PHOTO_PURPOSES = {
    "Tension Gauge Photos": "tension_gauge",
    "Overall Tower View":   "overall",
}


def _mime(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return MIME_MAP.get(ext, "application/octet-stream")


_MAX_PHOTO_DIM = 1600  # px, longest side


def _downscale_photo(fb: bytes, mime: str) -> tuple:
    """
    Phone photos routinely come in at 10-20+ MB / 4000px+ on a side. Keeping
    full-resolution originals in st.session_state for an entire wizard
    session (across every mod/position/special/extra photo slot), plus
    re-decoding them for every Gemini vision call, is what pushes a
    photo-heavy session over Streamlit Community Cloud's ~1GB free-tier
    memory limit and takes down the whole app ("Oh no. Error running app.").
    The report only ever embeds photos at 2.9"x2.6" (utils/docx_builder.py),
    so downscaling here is lossless for the actual output. Falls back to the
    original bytes if the file can't be decoded as an image (caller's
    st.image preview already has its own corrupt-file fallback).
    """
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(fb))
        img = ImageOps.exif_transpose(img)
        if max(img.size) > _MAX_PHOTO_DIM:
            img.thumbnail((_MAX_PHOTO_DIM, _MAX_PHOTO_DIM), Image.LANCZOS)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return fb, mime


def _tower_type() -> str:
    return st.session_state.project_info.get("tower_type", "Self Support")


def _friendly_ai_error(e: Exception) -> str:
    """
    Gemini errors come back as long raw API JSON blobs — fine for logs,
    unreadable for end users. Collapse the common cases to one clear
    sentence and log the full detail to the console (visible in Streamlit
    Cloud logs) for debugging.
    """
    import traceback
    print(f"[AI ERROR] {type(e).__name__}: {e}")
    traceback.print_exc()

    msg = str(e)
    if "RESOURCE_EXHAUSTED" in msg or "429" in msg or "quota" in msg.lower():
        return (
            "Gemini rate limit hit — this already retried a couple of times "
            "before giving up, so the API key's quota is genuinely exhausted "
            "for now (not just a brief burst). Wait a bit and try again, or "
            "check the key's plan & billing at https://aistudio.google.com/apikey."
        )
    if "API_KEY_INVALID" in msg or "401" in msg or "PERMISSION_DENIED" in msg:
        return "Gemini API key is invalid or missing permissions. Check GEMINI_API_KEY."
    return f"{msg[:200]} (see server logs for the full traceback)"


def _queue_warning(msg: str):
    """
    Upload processors call this instead of st.warning() directly when the
    warning happens right before an st.rerun() in the same script run —
    st.rerun() aborts the run immediately, so anything rendered just before
    it (including a plain st.warning()) is discarded and never reaches the
    browser. Queued warnings are flushed with _flush_warnings() on the next
    run, after the rerun completes, so the user actually sees them.
    """
    st.session_state.setdefault("_pending_warnings", []).append(msg)


def _flush_warnings():
    for msg in st.session_state.pop("_pending_warnings", []):
        st.warning(msg)


# ── Upload gallery helpers ───────────────────────────────────────────────────
# Factories (not bare closures inline in a loop) so each one binds its own
# doc_key / dict_key at creation time — avoids the classic Python
# late-binding-in-a-loop bug where every closure would end up sharing the
# *last* loop iteration's key.

def _make_doc_processor(doc_key: str):
    def _process(f, fb):
        mime = _mime(f.name)
        with st.spinner(f"Extracting data from {f.name}…"):
            try:
                extracted = extract_document_fields(fb, f.name, doc_key)
                st.session_state._doc_extractions[(doc_key, sig(f.name, fb))] = extracted
                st.toast(f"Extracted from {f.name}", icon="✅")
            except Exception as e:
                _queue_warning(f"Could not auto-extract from {f.name}: {_friendly_ai_error(e)}")
        return (fb, f.name, mime)
    return _process


def _make_plain_file_processor():
    def _process(f, fb):
        return (fb, f.name, _mime(f.name))
    return _process


def _make_doc_extraction_note(doc_key: str, items: list):
    def _note(idx, fname):
        fb = items[idx][0]
        extracted = st.session_state._doc_extractions.get((doc_key, sig(fname, fb)))
        if not extracted or "error" in extracted:
            return None
        parts = [f"{k}={v}" for k, v in extracted.items() if v and k != "raw_extract"]
        return "AI extracted: " + ", ".join(parts) if parts else None
    return _note


def _as_built_import_section(items: list):
    """
    Shows modifications the AI extracted from uploaded As-Built Drawings and
    lets the engineer import them into the Modifications list (Step 2) for
    review/editing there — the as-built drawing is the source of truth, but
    the engineer still confirms before anything is used in the report.
    """
    imported = st.session_state.setdefault("_as_built_imported", set())
    for fb, fname, _mime in items:
        key = ("as_built_drawings", sig(fname, fb))
        if key in imported:
            continue
        extracted = st.session_state._doc_extractions.get(key)
        found = (extracted or {}).get("modifications") or []
        found = [m for m in found if isinstance(m, dict) and m.get("description")]
        if not found:
            continue
        with st.container(border=True):
            st.markdown(f"**Modifications found in `{fname}`**")
            for m in found:
                pos = (m.get("position") or "").strip()
                st.caption(
                    f"• {f'[{pos}] ' if pos else ''}{m['description']}"
                    f" (elevation {m.get('elevation', 'n/a')})"
                )
            if st.button(f"➕ Add these {len(found)} to Modifications", key=f"import_asbuilt_{fname}"):
                mods = st.session_state.modifications
                start = len(mods)
                for i, m in enumerate(found):
                    pos = (m.get("position") or "").strip()
                    desc = m["description"].strip()
                    mods.append({
                        "mod_id": f"M{start + i + 1}",
                        "description": f"[{pos}] {desc}" if pos else desc,
                        "elevation": m.get("elevation", ""),
                    })
                st.session_state.modifications = mods
                st.session_state.obs_generated = False
                imported.add(key)
                st.success(f"Added {len(found)} modification(s) from {fname}. Review them on Step 2.")
                st.rerun()


def _make_list_delete(items: list):
    def _delete(idx):
        items.pop(idx)
    return _delete


def _make_list_edit(items: list):
    def _edit(idx, new_caption):
        # Editing the caption is treated as the engineer reviewing/resolving
        # any AI consistency flag on this photo, so it's cleared here.
        fb, _old_caption, mime, fname, *_flag = items[idx]
        items[idx] = (fb, new_caption, mime, fname, "")
    return _edit


def _doc_upload_section(doc_key: str, label: str, items: list, on_added):
    """
    Renders an "add files" uploader + persistent gallery for one document
    slot. `items` is the list currently stored for this slot (mutated via
    on_added when new files arrive). Runs AI field extraction only on
    genuinely new files — not on every rerun — which is also what keeps
    Gemini call volume from ballooning as the user works through the form.
    """
    uid = f"doc_{doc_key}"
    uploaded = st.file_uploader(
        f"Upload {label} (PDF, Word, or image)",
        type=["pdf", "docx", "jpg", "jpeg", "png"],
        key=uploader_key(uid),
        accept_multiple_files=True,
    )
    existing_sigs = sig_cache(uid)
    added = new_uploads(existing_sigs, uploaded, _make_doc_processor(doc_key))
    if added:
        on_added(added)
        bump_uploader(uid)
        st.rerun()

    render_file_gallery(
        items,
        on_delete=_make_list_delete(items),
        key_prefix=f"gal_{uid}",
        extraction_note=_make_doc_extraction_note(doc_key, items),
    )


def _photo_upload_section(uid: str, label: str, items: list, on_added, context: dict):
    """
    Renders an "add photos" uploader + persistent thumbnail gallery for one
    modification/position or special-photo slot. AI generates a caption for
    each photo and — when it's tied to a specific modification — flags if
    what's visible looks inconsistent with that modification's description
    (e.g. a horizontal member uploaded against a "diagonal bracing" mod).
    This is AI-suggests-only: the flag is a warning for the engineer to
    review, never an auto-reject. Captions stay editable either way, and
    editing a caption clears its flag (engineer has reviewed it).
    """
    uploaded = st.file_uploader(
        label, type=["jpg", "jpeg", "png"], accept_multiple_files=True,
        key=uploader_key(uid),
    )
    existing_sigs = sig_cache(uid)

    def _process(f, fb):
        fb, mime = _downscale_photo(fb, _mime(f.name))
        with st.spinner(f"Analyzing {f.name}…"):
            try:
                result = analyze_photo(fb, mime, context)
                caption, flag = result["caption"], result["flag"]
            except Exception as e:
                caption = context.get("fallback_caption", "Site photograph.")
                flag = ""
                _queue_warning(f"AI analysis failed for {f.name}: {_friendly_ai_error(e)}")
        return (fb, caption, mime, f.name, flag)

    added = new_uploads(existing_sigs, uploaded, _process)
    if added:
        on_added(added)
        bump_uploader(uid)
        st.rerun()

    render_photo_gallery(
        items, on_delete=_make_list_delete(items), key_prefix=f"gal_{uid}",
        on_edit=_make_list_edit(items),
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────

STEPS = [
    ("1", "Project Info"),
    ("2", "Modifications"),
    ("3", "Documents & Certs"),
    ("4", "Photographs"),
    ("5", "Review & Generate"),
]

with st.sidebar:
    st.markdown(f"""
    <div style="padding:1rem 0 1.1rem 0;border-bottom:1px solid rgba(29,78,216,0.2);margin-bottom:0.6rem;">
      <div style="display:flex;align-items:center;gap:0.6rem;margin-bottom:0.5rem;">
        <div style="background:rgba(29,78,216,0.20);border:1.5px solid rgba(29,78,216,0.45);
             border-radius:8px;padding:0.28rem 0.4rem;display:flex;align-items:center;flex-shrink:0;">
          {_LOGO_ICON}
        </div>
        <div>
          <div style="font-size:1.2rem;font-weight:900;color:#ffffff;letter-spacing:-0.5px;
               line-height:1;font-family:'Inter',sans-serif;">ATSS</div>
          <div style="font-size:0.55rem;color:#3b6ea8;text-transform:uppercase;letter-spacing:1.5px;
               margin-top:2px;font-family:'Inter',sans-serif;">Advanced Tower Structural</div>
        </div>
      </div>
      <div style="font-size:0.7rem;color:#4a6fa8;font-family:'Inter',sans-serif;
           background:rgba(29,78,216,0.08);border-radius:6px;padding:0.3rem 0.55rem;
           border:1px solid rgba(29,78,216,0.15);">
        PMI Closeout Report Generator
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f'<div style="font-size:0.6rem;font-weight:700;color:#2d4f7c;text-transform:uppercase;letter-spacing:1.2px;margin-bottom:0.4rem;font-family:\'Inter\',sans-serif;">Navigation</div>', unsafe_allow_html=True)

    for num, name in STEPS:
        n = int(num)
        cur = st.session_state.step
        if n < cur:
            circle_style = "background:#22c55e;border:none;"
            circle_inner = "✓"
            label_style  = "color:#86efac;font-weight:500;"
            row_style    = "background:rgba(34,197,94,0.06);"
        elif n == cur:
            circle_style = "background:linear-gradient(135deg,#1d4ed8,#3b82f6);border:none;box-shadow:0 2px 8px rgba(29,78,216,0.4);"
            circle_inner = str(n)
            label_style  = "color:#93c5fd;font-weight:700;"
            row_style    = "background:rgba(29,78,216,0.10);border:1px solid rgba(29,78,216,0.2);"
        else:
            circle_style = "background:transparent;border:1.5px solid rgba(255,255,255,0.15);"
            circle_inner = str(n)
            label_style  = "color:#4a6fa8;font-weight:400;"
            row_style    = ""
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:0.65rem;padding:0.42rem 0.6rem;
             border-radius:8px;margin-bottom:2px;{row_style}">
          <div style="width:26px;height:26px;{circle_style}border-radius:50%;display:flex;
               align-items:center;justify-content:center;font-size:0.7rem;color:#fff;
               font-weight:700;flex-shrink:0;font-family:'Inter',sans-serif;">{circle_inner}</div>
          <span style="font-size:0.82rem;{label_style}font-family:'Inter',sans-serif;">{name}</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
    if st.button("← Back", disabled=st.session_state.step == 1):
        st.session_state.step -= 1
        st.rerun()

    st.markdown("<div style='flex:1'></div>", unsafe_allow_html=True)

    # Tower type + site info cards
    tt = st.session_state.project_info.get("tower_type", "")
    if tt:
        tt_color = {"Self Support": "#3b82f6", "Guyed": "#8b5cf6", "Monopole": "#f59e0b"}.get(tt, "#3b82f6")
        st.markdown(f"""
        <div style="margin-top:1rem;padding:0.6rem 0.85rem;
             background:rgba(255,255,255,0.05);border-radius:9px;
             border:1px solid rgba(255,255,255,0.08);">
          <div style="font-size:0.58rem;color:#4a6fa8;text-transform:uppercase;
               letter-spacing:1px;font-family:'Inter',sans-serif;">Tower Type</div>
          <div style="font-size:0.88rem;color:{tt_color};font-weight:700;
               margin-top:3px;font-family:'Inter',sans-serif;">{tt}</div>
        </div>
        """, unsafe_allow_html=True)

    site = st.session_state.project_info.get("site_name", "")
    if site:
        st.markdown(f"""
        <div style="margin-top:0.4rem;padding:0.55rem 0.85rem;
             background:rgba(255,255,255,0.04);border-radius:9px;
             border:1px solid rgba(255,255,255,0.06);">
          <div style="font-size:0.58rem;color:#4a6fa8;text-transform:uppercase;
               letter-spacing:1px;font-family:'Inter',sans-serif;">Site</div>
          <div style="font-size:0.82rem;color:#c8d9f0;margin-top:2px;
               font-family:'Inter',sans-serif;">{site}</div>
        </div>
        """, unsafe_allow_html=True)

    # Signed-in user + logout
    auth_user = st.session_state.get("auth_user", "")
    st.markdown(f"""
    <div style="margin-top:1rem;padding:0.5rem 0.85rem;
         background:rgba(29,78,216,0.08);border-radius:9px;
         border:1px solid rgba(29,78,216,0.18);
         display:flex;align-items:center;gap:0.5rem;">
      <div style="width:22px;height:22px;background:rgba(29,78,216,0.3);border-radius:50%;
           display:flex;align-items:center;justify-content:center;font-size:0.7rem;
           color:#93c5fd;flex-shrink:0;">✦</div>
      <span style="font-size:0.76rem;color:#93b4d8;font-family:'Inter',sans-serif;">{auth_user}</span>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Sign Out", key="logout_btn"):
        st.session_state["authenticated"] = False
        st.session_state["auth_user"] = ""
        st.rerun()


# ── Step header + horizontal stepper ─────────────────────────────────────────

_STEP_LABELS = ["Project Info", "Modifications", "Docs & Certs", "Photographs", "Review & Generate"]

def _step_header(icon: str, title: str, subtitle: str = ""):
    cur = st.session_state.step
    step_items = []
    for i, label in enumerate(_STEP_LABELS, 1):
        if i < cur:
            circle_html = (
                f'<div class="atss-step-circle" style="background:#22c55e;border:none;">'
                f'<span style="color:white;font-size:0.72rem;">✓</span></div>'
            )
            label_html = f'<div class="atss-step-label" style="color:#22c55e;">{label}</div>'
            line_from = "#22c55e"
            line_to   = "#22c55e" if i + 1 < cur else "#1d4ed8"
        elif i == cur:
            circle_html = (
                f'<div class="atss-step-circle" style="background:linear-gradient(135deg,#1d4ed8,#3b82f6);'
                f'border:none;box-shadow:0 2px 10px rgba(29,78,216,0.40);">'
                f'<span style="color:white;">{i}</span></div>'
            )
            label_html = f'<div class="atss-step-label" style="color:#1d4ed8;font-weight:700;">{label}</div>'
            line_from = "#cbd5e1"
            line_to   = "#cbd5e1"
        else:
            circle_html = (
                f'<div class="atss-step-circle" style="background:#fff;border:2px solid #cbd5e1;">'
                f'<span style="color:#94a3b8;">{i}</span></div>'
            )
            label_html = f'<div class="atss-step-label" style="color:#94a3b8;">{label}</div>'
            line_from = "#cbd5e1"
            line_to   = "#cbd5e1"

        is_last = (i == len(_STEP_LABELS))
        connector = "" if is_last else (
            f'<div style="flex:1;height:2px;background:linear-gradient(90deg,{line_from},{line_to});'
            f'margin:0 0.15rem;margin-top:-1.1rem;"></div>'
        )
        step_items.append(
            f'<div style="display:flex;flex-direction:column;align-items:center;flex:1;">'
            f'{circle_html}{label_html}</div>'
        )
        if not is_last:
            step_items.append(
                f'<div style="flex:1;height:2px;background:linear-gradient(90deg,{line_from},{line_to});'
                f'margin-bottom:1.55rem;align-self:flex-end;min-width:10px;"></div>'
            )

    stepper_html = (
        '<div style="display:flex;align-items:flex-start;gap:0;padding:0 0.5rem;margin-bottom:1.4rem;">'
        + "".join(step_items)
        + "</div>"
    )

    sub = (
        f'<div style="font-size:0.83rem;color:rgba(255,255,255,0.72);margin-top:3px;'
        f'font-weight:400;font-family:\'Inter\',sans-serif;">{subtitle}</div>'
        if subtitle else ""
    )

    header_html = f"""
    <div style="background:linear-gradient(135deg,#0b1e40 0%,#1a3560 60%,#1d4ed8 100%);
         color:white;padding:1.1rem 1.6rem 1.3rem;border-radius:14px;margin-bottom:0.5rem;
         box-shadow:0 6px 24px rgba(10,30,70,0.20),0 2px 6px rgba(0,0,0,0.10);
         position:relative;overflow:hidden;">
      <div style="position:absolute;top:-20px;right:-10px;opacity:0.04;pointer-events:none;">
        {_TOWER_SVG.replace('viewBox="0 0 300 720"','viewBox="0 0 300 720" width="160" height="380"')}
      </div>
      <div style="position:relative;z-index:1;">
        <div style="font-size:0.62rem;font-weight:700;color:rgba(147,197,253,0.8);text-transform:uppercase;
             letter-spacing:1.5px;margin-bottom:0.35rem;font-family:'Inter',sans-serif;">
          Step {cur} of {len(_STEP_LABELS)}
        </div>
        <div style="font-size:1.18rem;font-weight:800;letter-spacing:-0.4px;
             font-family:'Inter',sans-serif;">{icon} {title}</div>
        {sub}
      </div>
    </div>
    """

    st.markdown(stepper_html + header_html, unsafe_allow_html=True)


def _card(content_fn, padding="1.4rem 1.6rem"):
    st.markdown(
        f'<div style="background:white;border-radius:12px;padding:{padding};'
        f'box-shadow:0 2px 12px rgba(10,30,70,0.07),0 1px 3px rgba(0,0,0,0.05);'
        f'border:1px solid #e1e8f2;margin-bottom:1rem;">',
        unsafe_allow_html=True
    )
    content_fn()
    st.markdown('</div>', unsafe_allow_html=True)


_flush_warnings()

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Project Information
# ═══════════════════════════════════════════════════════════════════════════════

if st.session_state.step == 1:
    _step_header("📋", "Step 1 — Project Information", "Enter the site details and tower configuration.")

    with st.expander("📂  Import from existing report (optional)", expanded=False):
        st.caption("Upload a pre-filled closeout report and all fields will be auto-populated.")
        prefilled_file = st.file_uploader(
            "Upload pre-filled report (.docx or .pdf)",
            type=["docx", "pdf"],
            key="prefilled_upload",
        )
        if prefilled_file and st.button("Extract & Pre-fill", key="btn_prefill"):
            with st.spinner("Extracting fields from document…"):
                try:
                    fb = prefilled_file.read()
                    extracted = extract_prefilled_report(fb, prefilled_file.name)
                    if "error" in extracted:
                        st.error(extracted["error"])
                    else:
                        info_keys = [
                            "report_date", "client", "site_name", "site_number",
                            "carrier_name", "site_address", "gps_coords", "tower_type",
                            "tower_height", "observation_date", "drawing_date",
                            "drawing_sheets", "general_contractor", "gc_contact",
                            "project_description",
                        ]
                        p_info = st.session_state.project_info.copy()
                        for k in info_keys:
                            if extracted.get(k):
                                p_info[k] = extracted[k]
                        st.session_state.project_info = p_info
                        mods = extracted.get("modifications", [])
                        if mods and isinstance(mods, list):
                            valid_mods = [m for m in mods if isinstance(m, dict) and m.get("description")]
                            if valid_mods:
                                for i, m in enumerate(valid_mods):
                                    m["mod_id"] = f"M{i+1}"
                                st.session_state.modifications = valid_mods
                        field_obs = extracted.get("field_observations", {})
                        if field_obs:
                            st.session_state.field_observations = field_obs
                            st.session_state.obs_generated = True
                        deficiencies = extracted.get("deficiencies", "").strip()
                        if deficiencies:
                            st.session_state.no_deficiencies = False
                            st.session_state.deficiencies = deficiencies
                        st.success(f"Fields extracted from {prefilled_file.name}. Review and edit below.")
                        st.rerun()
                except Exception as e:
                    st.error(f"Extraction failed: {_friendly_ai_error(e)}")

    st.markdown("---")
    p = st.session_state.project_info

    col1, col2 = st.columns(2)
    with col1:
        p["report_date"]      = st.text_input("Report Date", value=p.get("report_date", datetime.today().strftime("%B %d, %Y")))
        p["observation_date"] = st.text_input("Observation Date", value=p.get("observation_date", ""))
        p["client"]           = st.text_input("Client Name (To:)", value=p.get("client", ""))
        p["carrier_name"]     = st.text_input("Carrier Name", value=p.get("carrier_name", ""))
        p["site_name"]        = st.text_input("Site Name", value=p.get("site_name", ""))
        p["site_number"]      = st.text_input("Site Number / Job No", value=p.get("site_number", ""))

    with col2:
        p["site_address"]  = st.text_area("Site Address", value=p.get("site_address", ""), height=80)
        p["gps_coords"]    = st.text_input("GPS Coordinates", value=p.get("gps_coords", ""))
        prev_tower = p.get("tower_type", "Self Support")
        p["tower_type"]    = st.selectbox("Tower Type", TOWER_TYPES,
                                          index=TOWER_TYPES.index(prev_tower) if prev_tower in TOWER_TYPES else 0)
        p["tower_height"]  = st.text_input("Tower Height", value=p.get("tower_height", ""))
        p["drawing_sheets"] = st.text_input("Drawing Sheets (e.g. S-02, S-03)", value=p.get("drawing_sheets", ""))
        p["drawing_date"]  = st.text_input("Drawing Date", value=p.get("drawing_date", ""))

    if p.get("tower_type") == "Guyed":
        st.session_state.num_guys = st.number_input(
            "Number of Guy Anchors / Sets", min_value=1, max_value=12,
            value=st.session_state.num_guys, step=1,
        )

    st.markdown("---")
    col_gc1, col_gc2 = st.columns(2)
    with col_gc1:
        p["general_contractor"] = st.text_input("General Contractor", value=p.get("general_contractor", ""))
    with col_gc2:
        p["gc_contact"] = st.text_input("GC Contact / Phone", value=p.get("gc_contact", ""))

    p["project_description"] = st.text_area(
        "Project Description",
        value=p.get("project_description",
                    "Post modification structural reinforcement and verification of tower components as per approved design drawings."),
        height=80,
    )

    st.markdown("---")
    st.subheader("Observed Deficiencies")
    st.session_state.no_deficiencies = st.checkbox("No deficiencies observed", value=st.session_state.no_deficiencies)
    if not st.session_state.no_deficiencies:
        st.session_state.deficiencies = st.text_area(
            "List deficiencies (one per line)",
            value=st.session_state.deficiencies,
            height=100,
        )

    st.markdown("")
    if st.button("Next →", type="primary"):
        required = ["client", "site_name", "site_number", "tower_type", "observation_date"]
        missing = [f for f in required if not p.get(f)]
        if missing:
            st.error(f"Please fill in: {', '.join(missing)}")
        else:
            p["job_no"] = p["site_number"]
            st.session_state.project_info = p
            # Reset field observations if tower type changed
            if p["tower_type"] != prev_tower:
                st.session_state.field_observations = {}
                st.session_state.obs_generated = False
            st.session_state.step = 2
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Modifications
# ═══════════════════════════════════════════════════════════════════════════════

elif st.session_state.step == 2:
    _step_header("🔧", "Step 2 — Modifications", "Add each structural modification performed on this tower.")

    mods = st.session_state.modifications

    with st.expander("➕  Add Modification", expanded=len(mods) == 0):
        new_desc = st.text_area(
            "Description",
            placeholder='e.g. Adding redundant diagonal bracing of L2x2x3/16" (A572-50) Angle at each face.',
            key="new_desc", height=80,
        )
        new_elev = st.text_input("Elevation Range", placeholder="e.g. 200.0'-180.0'", key="new_elev")
        if st.button("Add Modification", type="primary"):
            if new_desc and new_elev:
                mod_id = f"M{len(mods)+1}"
                mods.append({"mod_id": mod_id, "description": new_desc, "elevation": new_elev})
                st.session_state.modifications = mods
                st.session_state.obs_generated = False
                st.rerun()
            else:
                st.error("Both description and elevation range are required.")

    if mods:
        st.markdown("##### Current Modifications")
        for i, mod in enumerate(mods):
            col1, col2, col3, col4 = st.columns([1, 5, 2, 1])
            col1.markdown(f"**{mod['mod_id']}**")
            col2.write(mod["description"])
            col3.caption(mod["elevation"])
            if col4.button("🗑", key=f"del_mod_{i}"):
                mods.pop(i)
                for j, m in enumerate(mods):
                    m["mod_id"] = f"M{j+1}"
                st.session_state.modifications = mods
                st.session_state.obs_generated = False
                st.rerun()

    st.markdown("---")
    if st.button("Next →", type="primary"):
        if not mods:
            st.error("Add at least one modification before continuing.")
        else:
            st.session_state.step = 3
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Documents & Certificates
# ═══════════════════════════════════════════════════════════════════════════════

elif st.session_state.step == 3:
    tower_type = _tower_type()
    _step_header(
        "📄", "Step 3 — Documents & Certificates",
        f"Upload supporting documents for this {tower_type} tower. Required documents are shown below.",
    )

    docs = st.session_state.documents
    required_docs = get_required_docs(tower_type)

    for doc_key, doc_label in required_docs:
        st.markdown(f"##### {doc_label}")
        items = docs.setdefault(doc_key, [])

        def _on_added(new_items, _dk=doc_key, _items=items):
            docs[_dk] = _items + new_items
            st.session_state.documents = docs

        _doc_upload_section(doc_key, doc_label, items, _on_added)
        if doc_key == "as_built_drawings":
            _as_built_import_section(items)
        st.markdown("---")

    st.markdown("##### Certificates & Additional Documents")
    st.caption(
        "Add each certificate or extra document with its own name (e.g. \"Welder Certification\", "
        "\"Tension Gauge Calibration Certificate\"). Each one becomes its own titled section in the "
        "report, listed by that name in the document and in Word's Table of Contents."
    )

    extra_docs = st.session_state.extra_documents

    for i, entry in enumerate(extra_docs):
        cols = st.columns([3, 4, 1])
        with cols[0]:
            entry["name"] = st.text_input(
                "Section name", value=entry.get("name", ""),
                placeholder="e.g. Welder Certification",
                key=f"extradoc_name_{i}", label_visibility="collapsed",
            )
        with cols[1]:
            items = entry.setdefault("files", [])
            uid = f"extradoc_{i}"
            uploaded = st.file_uploader(
                "Files", type=["pdf", "docx", "jpg", "jpeg", "png"],
                accept_multiple_files=True, key=uploader_key(uid),
                label_visibility="collapsed",
            )
            existing_sigs = sig_cache(uid)
            added = new_uploads(existing_sigs, uploaded, _make_plain_file_processor())
            if added:
                entry["files"] = items + added
                bump_uploader(uid)
                st.rerun()
        with cols[2]:
            if st.button("🗑️", key=f"extradoc_del_{i}"):
                extra_docs.pop(i)
                st.rerun()

        if entry.get("files"):
            render_file_gallery(
                entry["files"], on_delete=_make_list_delete(entry["files"]),
                key_prefix=f"gal_extradoc_{i}",
            )

    if st.button("+ Add certificate / document"):
        extra_docs.append({"name": "", "files": []})
        st.rerun()

    st.markdown("---")
    if st.button("Next →", type="primary"):
        st.session_state.step = 4
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Photographs
# ═══════════════════════════════════════════════════════════════════════════════

elif st.session_state.step == 4:
    tower_type = _tower_type()
    num_guys   = st.session_state.num_guys
    mods       = st.session_state.modifications
    photos     = st.session_state.photos

    positions = (
        ["Leg A", "Leg B", "Leg C"] if tower_type == "Self Support"
        else [f"Guy {i+1}" for i in range(num_guys)] if tower_type == "Guyed"
        else []
    )

    _step_header(
        "📷", "Step 4 — Site Photographs",
        "Upload photos for each modification and position. AI will auto-generate structural captions.",
    )

    def _make_photo_on_added(photos_dict, key):
        def _on_added(new_items):
            photos_dict[key] = photos_dict.get(key, []) + new_items
        return _on_added

    for mod in mods:
        mid = mod["mod_id"]
        st.markdown(f"##### {mid}: {mod['description'][:80]}{'…' if len(mod['description']) > 80 else ''}")

        if positions:
            tabs = st.tabs(positions)
            for tab, pos in zip(tabs, positions):
                with tab:
                    key = (mid, pos)
                    context = {
                        "mod_id": mid, "mod_desc": mod["description"],
                        "elevation": mod["elevation"], "position": pos,
                        "tower_type": tower_type, "photo_purpose": "modification",
                        "fallback_caption": f"{mid} {pos} — {mod['description']}",
                    }
                    _photo_upload_section(
                        f"photo_{mid}_{pos}", f"Photos — {mid} {pos}",
                        photos.get(key, []), _make_photo_on_added(photos, key), context,
                    )
        else:
            key = (mid, "")
            context = {
                "mod_id": mid, "mod_desc": mod["description"],
                "elevation": mod["elevation"], "position": "",
                "tower_type": tower_type, "photo_purpose": "modification",
                "fallback_caption": f"{mid} — {mod['description']}",
            }
            _photo_upload_section(
                f"photo_{mid}", f"Photos — {mid}",
                photos.get(key, []), _make_photo_on_added(photos, key), context,
            )

        st.markdown("---")

    st.session_state.photos = photos

    # Special photo sections — differ by tower type
    st.markdown("### Additional Photo Sections")
    special_labels = get_special_photos(tower_type)
    special_photos = st.session_state.special_photos

    for label in special_labels:
        st.markdown(f"##### {label}")
        purpose = GUYED_PHOTO_PURPOSES.get(label, "overall")
        slug = label.lower().replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "").replace("&", "")
        context = {
            "photo_purpose": purpose, "tower_type": tower_type,
            "fallback_caption": f"{label} — site photograph.",
        }
        _photo_upload_section(
            f"photo_special_{slug}", f"Upload photos — {label}",
            special_photos.get(label, []), _make_photo_on_added(special_photos, label), context,
        )
        st.markdown("---")

    st.session_state.special_photos = special_photos

    # Extra Photos — user-named, not a fixed special-photo slot. Mirrors the
    # "Certificates & Additional Documents" pattern on Step 3: the engineer
    # names the section, uploads photos, and it's auto-added to the report's
    # Photo Documentation table and given its own photo group heading.
    st.markdown("### Extra Photos")
    st.caption(
        "Add any additional photo group with its own name (e.g. \"Drone Overview\", "
        "\"Site Access Conditions\"). Each one gets its own heading in the report and "
        "its own row in the Photo Documentation table."
    )

    extra_photos = st.session_state.extra_photos

    for i, entry in enumerate(extra_photos):
        cols = st.columns([4, 1])
        with cols[0]:
            entry["name"] = st.text_input(
                "Section name", value=entry.get("name", ""),
                placeholder="e.g. Drone Overview",
                key=f"extraphoto_name_{i}",
            )
        with cols[1]:
            if st.button("🗑️ Remove", key=f"extraphoto_del_{i}"):
                extra_photos.pop(i)
                st.rerun()

        entry_photos = entry.setdefault("photos", [])
        context = {
            "photo_purpose": "overall", "tower_type": tower_type,
            "fallback_caption": f"{entry.get('name') or 'Extra photo'} — site photograph.",
        }
        _photo_upload_section(
            f"extraphoto_{i}", f"Upload photos — {entry.get('name') or f'Section {i + 1}'}",
            entry_photos, _make_photo_on_added(entry, "photos"), context,
        )
        st.markdown("---")

    if st.button("+ Add extra photo section"):
        extra_photos.append({"name": "", "photos": []})
        st.rerun()

    st.session_state.extra_photos = extra_photos

    if st.button("Next →", type="primary"):
        st.session_state.step = 5
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Review & Generate
# ═══════════════════════════════════════════════════════════════════════════════

elif st.session_state.step == 5:
    info       = st.session_state.project_info
    mods       = st.session_state.modifications
    tower_type = info.get("tower_type", "Self Support")

    _step_header("📋", "Step 5 — Review & Generate", "Review your submission, edit AI observations if needed, then generate the report.")

    # ── Build check data ──────────────────────────────────────────────────────
    check_data = {
        "tower_type":    tower_type,
        "modifications": mods,
        "num_guys":      st.session_state.num_guys,
        "photos":        dict(st.session_state.photos),
        "documents":     st.session_state.documents,
        "extra_documents": st.session_state.extra_documents,
    }
    special = st.session_state.special_photos
    for label, pl in special.items():
        if pl:
            check_data["photos"][("special", label)] = pl

    missing = check_missing_items(check_data)
    total_missing = sum(len(v) for v in missing.values())

    # ── Project Summary card ──────────────────────────────────────────────────
    col_sum, col_docs = st.columns(2)

    with col_sum:
        st.markdown("""
        <div style="background:white;border-radius:12px;padding:1.3rem 1.5rem;
             box-shadow:0 2px 10px rgba(0,0,0,0.06);border:1px solid #e4ecf7;margin-bottom:1rem;">
          <div style="font-size:0.7rem;font-weight:700;color:#6b7fa8;text-transform:uppercase;
               letter-spacing:1px;margin-bottom:0.75rem;">Project Summary</div>
        """, unsafe_allow_html=True)
        fields = [
            ("Site", f"{info.get('site_name', '—')} ({info.get('site_number', '—')})"),
            ("Client", info.get("client", "—")),
            ("Carrier", info.get("carrier_name", "—")),
            ("Tower", f"{tower_type}, {info.get('tower_height', '—')}"),
            ("Observation Date", info.get("observation_date", "—")),
            ("Modifications", str(len(mods))),
            ("General Contractor", info.get("general_contractor", "—")),
        ]
        for label, val in fields:
            st.markdown(f"""
            <div style="display:flex;justify-content:space-between;padding:0.3rem 0;
                 border-bottom:1px solid #f0f4f8;font-size:0.875rem;">
              <span style="color:#6b7fa8;font-weight:500;">{label}</span>
              <span style="color:#1e293b;font-weight:500;text-align:right;">{val}</span>
            </div>
            """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with col_docs:
        required_docs = get_required_docs(tower_type)
        rows_html = ""
        for doc_key, doc_label in required_docs:
            uploaded = bool(st.session_state.documents.get(doc_key))
            badge = ('<span style="background:#dcfce7;color:#166534;font-size:0.72rem;font-weight:700;'
                     'padding:2px 9px;border-radius:20px;">✓ Uploaded</span>' if uploaded
                     else '<span style="background:#fee2e2;color:#991b1b;font-size:0.72rem;font-weight:700;'
                     'padding:2px 9px;border-radius:20px;">✗ Missing</span>')
            rows_html += (
                f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'padding:0.35rem 0;border-bottom:1px solid #f0f4f8;font-size:0.85rem;">'
                f'<span style="color:#374151;">{doc_label}</span>{badge}</div>'
            )

        cert_count = len([e for e in st.session_state.extra_documents if e.get("name", "").strip() and e.get("files")])
        cert_badge = (f'<span style="background:#dcfce7;color:#166534;font-size:0.72rem;font-weight:700;'
                      f'padding:2px 9px;border-radius:20px;">✓ {cert_count} uploaded</span>' if cert_count
                      else '<span style="background:#fee2e2;color:#991b1b;font-size:0.72rem;font-weight:700;'
                      'padding:2px 9px;border-radius:20px;">✗ Missing</span>')
        rows_html += (
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:0.35rem 0;font-size:0.85rem;margin-top:0.25rem;">'
            f'<span style="color:#374151;font-weight:500;">Certificates & Extra Docs</span>{cert_badge}</div>'
        )

        st.markdown(
            f'<div style="background:white;border-radius:12px;padding:1.3rem 1.5rem;'
            f'box-shadow:0 2px 10px rgba(0,0,0,0.06);border:1px solid #e4ecf7;margin-bottom:1rem;">'
            f'<div style="font-size:0.7rem;font-weight:700;color:#6b7fa8;text-transform:uppercase;'
            f'letter-spacing:1px;margin-bottom:0.75rem;">Document Checklist</div>'
            f'{rows_html}</div>',
            unsafe_allow_html=True,
        )

    # ── Missing items card ────────────────────────────────────────────────────
    if total_missing == 0:
        st.markdown("""
        <div style="background:#f0fdf4;border:1.5px solid #4ade80;border-radius:10px;
             padding:0.9rem 1.4rem;margin:0.5rem 0 1rem 0;display:flex;align-items:center;gap:0.75rem;">
          <span style="font-size:1.3rem;">✅</span>
          <div>
            <div style="font-weight:700;color:#15803d;font-size:0.95rem;">All Required Items Present</div>
            <div style="color:#16a34a;font-size:0.82rem;margin-top:2px;">Report is ready to generate with complete data.</div>
          </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        sections_html = ""
        icons = {"photos": "📷", "documents": "📄", "certificates": "🏆"}
        for category, items in missing.items():
            if items:
                items_str = " &nbsp;·&nbsp; ".join(items)
                sections_html += (
                    f'<div style="margin-top:0.6rem;">'
                    f'<div style="font-size:0.78rem;font-weight:700;color:#92400e;text-transform:uppercase;letter-spacing:0.5px;">{icons.get(category,"")} {category}</div>'
                    f'<div style="font-size:0.83rem;color:#78350f;margin-top:3px;line-height:1.6;">{items_str}</div>'
                    f'</div>'
                )

        st.markdown(
            f'<div style="background:#fffbeb;border:1.5px solid #f59e0b;border-radius:10px;'
            f'padding:1rem 1.4rem;margin:0.5rem 0 1rem 0;">'
            f'<div style="font-weight:700;color:#92400e;font-size:0.95rem;margin-bottom:0.25rem;">'
            f'⚠️ &nbsp;{total_missing} Item{"s" if total_missing > 1 else ""} Missing</div>'
            f'<div style="font-size:0.8rem;color:#a16207;">'
            f'The report can still be generated, but the following sections will show [Not provided].</div>'
            f'{sections_html}</div>',
            unsafe_allow_html=True,
        )

    # ── Plumb & Twist / Tension vs. As-Built cross-check (Guyed only) ─────────
    if tower_type == "Guyed":
        mismatches = (
            cross_check_plumb_twist(st.session_state._doc_extractions)
            + cross_check_tension(st.session_state._doc_extractions)
        )
        if mismatches:
            items_html = "".join(
                f'<div style="margin-top:0.3rem;font-size:0.83rem;color:#78350f;">• {m}</div>'
                for m in mismatches
            )
            st.markdown(
                f'<div style="background:#fffbeb;border:1.5px solid #f59e0b;border-radius:10px;'
                f'padding:1rem 1.4rem;margin:0.5rem 0 1rem 0;">'
                f'<div style="font-weight:700;color:#92400e;font-size:0.95rem;">'
                f'⚠️ &nbsp;Guy Report / As-Built Position Mismatch</div>'
                f'{items_html}</div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ── Field Observation Details — AI generated + editable ──────────────────
    st.markdown("""
    <div style="font-size:1rem;font-weight:700;color:#1e293b;margin-bottom:0.25rem;">
      🔍 Field Observation Details
    </div>
    <div style="font-size:0.82rem;color:#64748b;margin-bottom:0.75rem;">
      AI-generated based on your modifications. Edit any section before generating the report.
    </div>
    """, unsafe_allow_html=True)

    obs_sections = OBS_SECTIONS_BY_TOWER.get(tower_type, OBS_SECTIONS_BY_TOWER["Self Support"])

    col_gen_obs, col_regen = st.columns([3, 1])
    with col_gen_obs:
        if not st.session_state.obs_generated or not st.session_state.field_observations:
            if st.button("✨  Generate AI Observations", type="primary", key="btn_gen_obs"):
                with st.spinner("Generating field observations with AI…"):
                    try:
                        obs = generate_field_observations(mods, tower_type)
                        st.session_state.field_observations = obs or {s: ["", ""] for s in obs_sections}
                        st.session_state.obs_gen_error = None if obs else "AI returned no observations."
                    except Exception as e:
                        st.session_state.field_observations = {s: ["", ""] for s in obs_sections}
                        st.session_state.obs_gen_error = _friendly_ai_error(e)
                    st.session_state.obs_generated = True
                    st.rerun()
    with col_regen:
        if st.session_state.obs_generated:
            if st.button("🔄  Regenerate", key="btn_regen_obs"):
                with st.spinner("Regenerating…"):
                    try:
                        obs = generate_field_observations(mods, tower_type)
                        if obs:
                            st.session_state.field_observations = obs
                            st.session_state.obs_gen_error = None
                        else:
                            st.session_state.obs_gen_error = "AI returned no observations."
                    except Exception as e:
                        st.session_state.obs_gen_error = _friendly_ai_error(e)
                    st.rerun()

    # Persisted across the rerun above — a warning shown right before st.rerun()
    # would otherwise be wiped before the user ever sees it.
    if st.session_state.get("obs_gen_error"):
        st.warning(f"{st.session_state.obs_gen_error} You can type observations manually below.")

    if st.session_state.obs_generated and st.session_state.field_observations:
        field_obs = st.session_state.field_observations
        for i, section in enumerate(obs_sections):
            bullets = field_obs.get(section, ["", ""])
            current_text = "\n".join(bullets) if isinstance(bullets, list) else str(bullets)
            st.markdown(f"""
            <div style="font-size:0.82rem;font-weight:700;color:#1e3a6b;margin:0.75rem 0 0.2rem 0;
                 text-transform:uppercase;letter-spacing:0.4px;">{section}</div>
            """, unsafe_allow_html=True)
            st.text_area(
                label=section,
                value=current_text,
                height=80,
                key=f"obs_edit_{i}",
                label_visibility="collapsed",
            )
    elif not st.session_state.obs_generated:
        st.info("Click **Generate AI Observations** above to create field observation notes, or skip to generate the report without them.")

    st.markdown("---")

    # ── Generate Report ───────────────────────────────────────────────────────
    st.markdown("### Generate Report")
    generate = st.button("📄  Generate Report", type="primary")

    if generate:
        # Collect current text area values → rebuild field_observations dict
        final_obs = {}
        if st.session_state.obs_generated and st.session_state.field_observations:
            for i, section in enumerate(obs_sections):
                raw = st.session_state.get(f"obs_edit_{i}", "")
                bullets = [
                    ln.strip().lstrip("•–- ").strip()
                    for ln in raw.split("\n") if ln.strip()
                ]
                final_obs[section] = bullets

        deficiencies = "" if st.session_state.no_deficiencies else st.session_state.deficiencies

        with st.spinner("Building report…"):
            try:
                report_bytes = build_report({
                    "info":               info,
                    "modifications":      mods,
                    "photos":             st.session_state.photos,
                    "special_photos":     st.session_state.special_photos,
                    "extra_photos":       [
                        (e["name"], e["photos"]) for e in st.session_state.extra_photos
                        if e.get("name", "").strip() and e.get("photos")
                    ],
                    "documents":          st.session_state.documents,
                    "extra_documents":    [
                        (e["name"], e["files"]) for e in st.session_state.extra_documents
                        if e.get("name", "").strip() and e.get("files")
                    ],
                    "deficiencies":       deficiencies,
                    "no_deficiencies":    st.session_state.no_deficiencies,
                    "tower_type":         tower_type,
                    "num_guys":           st.session_state.num_guys,
                    "field_observations": final_obs,
                })
                filename = f"{info.get('site_number', 'report')} PMI Closeout Report.docx"
                st.success("✅  Report generated successfully!")
                st.download_button(
                    label="⬇️  Download Report (.docx)",
                    data=report_bytes,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            except Exception as e:
                st.error(f"Report generation failed: {_friendly_ai_error(e)}")
