# server.py  — Dave-PMEA (full, paste-in replacement)
# - FastAPI app with:
#   • PMEA loop (draft → critique → revise)
#   • Per-user memory (SQLite) → /memory?user_id=…
#   • Age verify + ultra-safe modes (child/teen/adult)
#   • Test endpoints + OpenAPI servers fix (for GPT Actions import)
#   • CORS enabled (so ChatGPT Actions can call it)

from fastapi import FastAPI, Request, Body
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import sqlite3, re, os

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(title="Dave-PMEA", version="1.0.0", description="PMEA demo API")

# CORS (keep simple; you can lock this down later)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# DB (SQLite) — per-user memory + users table
# -----------------------------------------------------------------------------
DB_PATH = "dave_memory.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Per-user memory
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role    TEXT,
            text    TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Users (for age + verification + mode)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            age     INTEGER,
            verified INTEGER DEFAULT 0,
            mode    TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def save_memory(user_id: str, role: str, text: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO memory (user_id, role, text) VALUES (?, ?, ?)",
              (user_id, role, text))
    conn.commit()
    conn.close()

def fetch_memory(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT role, text, timestamp
        FROM memory
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT ?
    """, (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return [{"role": r[0], "text": r[1], "timestamp": r[2]} for r in rows]

def set_user(user_id: str, age: int, verified: bool, mode: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO users (user_id, age, verified, mode)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            age=excluded.age,
            verified=excluded.verified,
            mode=excluded.mode
    """, (user_id, age, int(verified), mode))
    conn.commit()
    conn.close()

def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, age, verified, mode FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {"user_id": row[0], "age": row[1], "verified": bool(row[2]), "mode": row[3]}

# -----------------------------------------------------------------------------
# Safety / Modes
# -----------------------------------------------------------------------------
ALLOWED_CHILD_TOPICS = {
    "space", "planets", "stars", "animals", "dinosaurs", "math", "reading",
    "history (general)", "science for kids"
}

PII_PATTERNS = [
    r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b",   # SSN-like
    r"\b\d{10,16}\b",                   # long digit strings (phone/card)
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    r"https?://\S+",
]
PII_REGEX = [re.compile(p, re.IGNORECASE) for p in PII_PATTERNS]

def determine_mode(age: Optional[int]) -> str:
    if age is None:
        return "adult"      # default if unknown
    if age < 13:
        return "child"
    if age < 18:
        return "teen"
    return "adult"

def sanitize_text_for_teen(text: str) -> str:
    # Strip links & obvious PII tokens; keep short
    t = text
    for rx in PII_REGEX:
        t = rx.sub("[redacted]", t)
    # keep it concise
    return t[:500]

def ultra_safe_reply(user_message: str, mode: str) -> str:
    if mode == "child":
        # Allow-list simple topics; otherwise redirect
        topic = user_message.lower()
        allowed = any(key in topic for key in ALLOWED_CHILD_TOPICS)
        if not allowed:
            return ("I can help with safe topics like space, animals, math, "
                    "reading, and simple science. For other things, please ask a trusted adult.")
        # Give a short, gentle educational reply
        return ("Here’s a kid-friendly explanation:\n"
                f"• {user_message.strip().capitalize()} is interesting!\n"
                "• Let’s explore it simply and safely.\n"
                "• Do you want a short fact list or a mini story?")
    elif mode == "teen":
        return sanitize_text_for_teen(
            "Let’s keep this short and safe. "
            "I’ll give you the key points and next steps to learn more."
        )
    else:
        # adult → normal
        return "Okay—what’s the exact task and target output?"

# -----------------------------------------------------------------------------
# PMEA loop (small, fast)
# -----------------------------------------------------------------------------
def pmea_reply(message: str) -> str:
    # DRAFT
    draft = f"Draft: {message}"
    # CRITIQUE
    issues = []
    if len(message) < 6:
        issues.append("too short")
    if "?" not in message and "help" not in message.lower():
        issues.append("may lack clear ask")
    critique = f"Issues: {', '.join(issues) or 'none'}"
    # REVISE
    tip = "Tip: tell me the exact task + output format."
    revise = f"Improved reply: {message}\n{tip}"
    return revise

# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------
class AgeVerifyIn(BaseModel):
    user_id: str
    age: int

class ChatIn(BaseModel):
    user_id: str
    message: str
    dob: Optional[str] = None  # not used for mode (age verify does that); kept for context if you want it later

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <h3>✅ Dave-PMEA is running.</h3>
    <ul>
      <li>GET  <code>/ping</code></li>
      <li>GET  <code>/healthz</code></li>
      <li>POST <code>/age-verify</code>  (json: {"user_id","age"})</li>
      <li>POST <code>/chat</code>        (json: {"user_id","message"})</li>
      <li>GET  <code>/memory?user_id=...&limit=20</code></li>
      <li>GET  <code>/openapi.json</code> (for GPT Actions “Import from URL”)</li>
      <li>GET  <code>/test</code> (simple form)</li>
    </ul>
    """

@app.get("/ping")
def ping():
    return {"ok": True}

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/age-verify")
def age_verify(payload: AgeVerifyIn):
    mode = determine_mode(payload.age)
    set_user(payload.user_id, payload.age, verified=True, mode=mode)
    return {"ok": True, "user": payload.user_id, "age": payload.age, "mode": mode}

@app.post("/chat")
def chat(payload: ChatIn):
    # find or default user record
    u = get_user(payload.user_id)
    mode = u["mode"] if u else "adult"

    # ultra-safe entry wrapper
    guard = ultra_safe_reply(payload.message, mode)

    # produce answer (PMEA) then post-filter if needed
    revised = pmea_reply(payload.message)

    if mode == "child":
        # Child: we do NOT store memory and return the safe wrapper (short reply).
        # You can also return a mini educational answer here if desired.
        return {"reply": guard, "mode": mode, "stored": False}

    # Teen: store but keep outcomes short/sanitized
    if mode == "teen":
        out = sanitize_text_for_teen(revised)
        save_memory(payload.user_id, "user", payload.message)
        save_memory(payload.user_id, "assistant", out)
        return {"reply": out, "mode": mode, "stored": True}

    # Adult: normal behaviour + memory
    save_memory(payload.user_id, "user", payload.message)
    save_memory(payload.user_id, "assistant", revised)
    return {"reply": revised, "mode": mode, "stored": True}

# Back-compat alias if you want /api/chat too
@app.post("/api/chat")
def chat_alias(payload: ChatIn):
    return chat(payload)

@app.get("/memory")
def memory(user_id: str, limit: int = 20):
    # Child → intentionally returns empty by policy
    u = get_user(user_id)
    if u and u["mode"] == "child":
        return {"history": []}
    return {"history": fetch_memory(user_id, limit)}

# Tiny test UI
@app.get("/test", response_class=HTMLResponse)
def test_page():
    return """
    <h3>Dave quick test</h3>
    <form method="post" action="/chat" onsubmit="event.preventDefault(); send();">
      <label>User ID <input id="uid" value="phil-ipad"></label><br/>
      <label>Message <input id="msg" value="Hello Dave — help me build a recursive assistant."></label><br/>
      <button>Send</button>
    </form>
    <pre id="out"></pre>
    <script>
    async function send(){
      const r = await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},
        body: JSON.stringify({user_id: document.getElementById('uid').value,
                              message: document.getElementById('msg').value})});
      document.getElementById('out').textContent = await r.text();
    }
    </script>
    """

# -----------------------------------------------------------------------------
# OpenAPI "servers" fix so GPT Builder can import cleanly
# -----------------------------------------------------------------------------
BASE_URL = os.getenv("APP_BASE_URL", "https://dave-pmea.onrender.com")

from fastapi.openapi.utils import get_openapi
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["servers"] = [{"url": BASE_URL}]
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi
