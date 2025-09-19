import os, re, sqlite3
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# -------- Config --------
APP_URL = os.getenv("APP_URL", "https://dave-pmea.onrender.com")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # used if OPENAI_API_KEY is set

# -------- App --------
app = FastAPI(
    title="Dave-PMEA Ultra-Safe",
    description="PMEA demo API with per-user memory and Ultra-Safe age modes",
    version="1.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later to your domain(s)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------- DB --------
def init_db():
    conn = sqlite3.connect("dave_memory.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            age INTEGER,
            verified INTEGER DEFAULT 0,
            mode TEXT DEFAULT 'adult'  -- adult | teen | child | blocked
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            text TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def set_user(user_id: str, age: int):
    """
    Ultra-Safe policy:
      - age >= 18  -> verified=1, mode='adult'
      - 13 <= age < 18 -> verified=1, mode='teen'
      - age < 13 -> verified=1, mode='child' (ultra-safe; no persistent memory)
    """
    if age >= 18:
        verified, mode = 1, "adult"
    elif age >= 13:
        verified, mode = 1, "teen"
    else:
        verified, mode = 1, "child"

    conn = sqlite3.connect("dave_memory.db")
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO users (user_id, age, verified, mode) VALUES (?,?,?,?)",
        (user_id, age, verified, mode),
    )
    conn.commit()
    conn.close()
    return {"verified": bool(verified), "mode": mode, "age": age}

def get_user(user_id: str):
    conn = sqlite3.connect("dave_memory.db")
    c = conn.cursor()
    c.execute("SELECT age, verified, mode FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    age, verified, mode = row
    return {"age": age, "verified": bool(verified), "mode": mode}

def save_memory(user_id: str, role: str, text: str):
    conn = sqlite3.connect("dave_memory.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO memory (user_id, role, text) VALUES (?,?,?)",
        (user_id, role, text),
    )
    conn.commit()
    conn.close()

def load_memory(user_id: str, limit: int = 20):
    conn = sqlite3.connect("dave_memory.db")
    c = conn.cursor()
    c.execute(
        "SELECT role, text, timestamp FROM memory WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows = c.fetchall()
    conn.close()
    return [{"role": r, "text": t, "timestamp": ts} for (r, t, ts) in rows]

# -------- Safety Filters --------
PROFANITY = re.compile(r"\b(fuck|shit|cunt|bitch|bastard|dick|asshole|wank|prick)\b", re.IGNORECASE)
URLS = re.compile(r"https?://\S+")
PII = re.compile(r"\b(\d{3}[-.\s]?\d{3}[-.\s]?\d{4}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")

# Topics not suitable for teens
DISALLOWED_TEEN = {
    "explicit sexual", "porn", "adult content",
    "detailed drug how-to", "weapon making", "self-harm instructions",
    "real-money gambling tips", "deepfake creation", "hacking tutorials",
}

# Topics allowed for child (strict allow-list)
ALLOWED_CHILD = {
    "homework", "math", "science", "history", "geography", "reading", "writing",
    "spelling", "study skills", "school projects", "sports rules", "music basics",
    "art basics", "healthy habits", "time management", "friendship skills",
    "online safety", "bullying support", "feelings", "emotion regulation",
    "asking for help", "curiosity questions", "kid-safe facts",
}

def scrub_user_text_for_storage(text: str) -> str:
    # Remove URLs & PII before storing anything for minors
    t = URLS.sub("[link removed]", text)
    t = PII.sub("[private removed]", t)
    return t

def teen_guard(text: str) -> str:
    t = scrub_user_text_for_storage(text)
    return PROFANITY.sub("[bleep]", t)

def teen_blocks(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in DISALLOWED_TEEN)

def child_allowed(text: str) -> bool:
    low = text.lower()
    return any(topic in low for topic in ALLOWED_CHILD)

def teen_sanitize_reply(reply: str) -> str:
    reply = URLS.sub("[link removed]", reply)
    reply = PII.sub("[private removed]", reply)
    reply = PROFANITY.sub("[bleep]", reply)
    if len(reply) > 700:
        reply = reply[:680].rstrip() + "…"
    return (
        "Here’s a safe, age-appropriate answer:\n"
        + reply
        + "\n\nIf this involves health, safety, or personal concerns, please talk with a parent/guardian or trusted adult."
    )

def child_reply(user_text: str) -> str:
    # Very short, supportive, educational, and safe
    return (
        "I can help with school topics and kid-safe questions. "
        "Try asking about homework, science, reading, history, or healthy habits. "
        "If your question feels personal or tricky, please ask a parent/guardian or teacher to help you."
    )

# -------- PMEA reply (with optional OpenAI) --------
def pmea_style_reply(prompt: str, mode: str, context_shards: List[str]) -> str:
    """
    If OPENAI_API_KEY is present, call OpenAI for a concise answer.
    Otherwise, return a local structured stub so the API still works.
    """
    intro = ""
    if context_shards:
        intro = "Recent context:\n- " + "\n- ".join(context_shards[:6]) + "\n\n"

    if not OPENAI_API_KEY:
        # Local stub
        return (
            f"{intro}"
            f"Answer (local): I understood your request: '{prompt}'. "
            f"I will keep it {('extra safe' if mode in ['teen','child'] else 'clear and practical')} and concise. "
            f"Tell me the exact outcome you want and who it’s for."
        )

    # Live call to OpenAI (minimal)
    try:
        # Lazy import to avoid dependency when key not set
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        system = (
            "You are Dave — a clear, structured assistant. "
            "Keep answers short, practical, and safe. "
            "Always prefer step-by-step with: What it is → How to do it. "
            "No medical, legal, or adult content for minors."
        )
        user = f"{intro}{prompt}"

        res = client.chat.completions.create(
            model=MODEL,
            temperature=0.3,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (res.choices[0].message.content or "").strip()
    except Exception as e:
        return (
            f"{intro}Answer: I understood your request but could not reach the model just now. "
            f"Error: {e}. I’ll give a brief local suggestion: "
            f"Break your goal into 2–3 steps and ask me for the first step in detail."
        )

# -------- Schemas --------
class AgeVerifyIn(BaseModel):
    user_id: str
    age: int

class ChatIn(BaseModel):
    user_id: str
    message: str
    limit: Optional[int] = 10  # for context recall

# -------- Routes --------
@app.get("/")
def root():
    return {"ok": True, "msg": "Dave/PMEA Ultra-Safe API running.", "openapi": f"{APP_URL}/openapi.json"}

@app.get("/status")
def status():
    return {
        "ok": True,
        "app": "Dave-PMEA Ultra-Safe",
        "version": "1.2.0",
        "has_openai": bool(OPENAI_API_KEY),
        "model": MODEL if OPENAI_API_KEY else None,
    }

@app.post("/age-verify")
def age_verify(body: AgeVerifyIn):
    if not body.user_id or body.age is None:
        return JSONResponse({"ok": False, "error": "user_id and age are required"}, status_code=400)
    info = set_user(body.user_id, body.age)
    return {"ok": True, "user": info}

@app.get("/memory")
def memory(user_id: str, limit: int = 20):
    user = get_user(user_id)
    if not user:
        return JSONResponse({"ok": False, "error": "unknown user_id"}, status_code=404)
    # child mode: no memory is stored
    if user["mode"] == "child":
        return {"ok": True, "user_mode": "child", "items": []}
    items = load_memory(user_id, limit=limit)
    return {"ok": True, "user_mode": user["mode"], "items": items}

@app.post("/chat")
def chat(body: ChatIn):
    # ensure user exists
    user = get_user(body.user_id)
    if not user:
        # default to child if unknown age (ultra safe)
        set_user(body.user_id, 10)
        user = get_user(body.user_id)

    mode = user["mode"]
    raw_text = body.message.strip()

    # select context shards (private per-user)
    context_items = load_memory(body.user_id, limit=body.limit or 10)
    context_shards = []
    for it in context_items:
        # Only assistant/user message text; keep short
        text = (it["text"] or "").strip()
        if text:
            context_shards.append(text[:160])

    # Route by mode
    if mode == "child":
        # no persistent memory; extremely safe
        if not child_allowed(raw_text):
            reply = child_reply(raw_text)
        else:
            # Generate a kid-safe short answer (local/OpenAI), then clamp length and add adult guidance
            base = pmea_style_reply(raw_text, mode, context_shards)
            base = URLS.sub("[link removed]", base)
            base = PII.sub("[private removed]", base)
            if len(base) > 500:
                base = base[:480].rstrip() + "…"
            reply = (
                base
                + "\n\nRemember: if something feels confusing or personal, please ask a parent/guardian or teacher to help."
            )

        # Do NOT store memory for child mode
        done = reply
        markers = {
            "✅ Done": done,
            "⏳ Next": "Ask about homework, school projects, or a kid-safe topic.",
            "❌ Blockers": "I avoid grown-up topics in Ultra-Safe mode.",
            "♻️ Compression": "Short, child-safe reply.",
            "🌌 Archive": "(not stored for under 13)",
            "🌀 Spiral": "Not triggered",
            "mode": mode,
        }
        return {"ok": True, "response": reply, "markers": markers}

    if mode == "teen":
        # block disallowed teen topics; sanitize input and reply; trim storage
        if teen_blocks(raw_text):
            safe_msg = (
                "I can’t help with that topic in teen mode. "
                "I can support study help, wellbeing basics, and safe life skills. "
                "If this is important, please talk with a trusted adult."
            )
            reply = teen_sanitize_reply(safe_msg)
            # Store only a minimal assistant note (no user content)
            save_memory(body.user_id, "assistant", "(Teen-safe refusal issued)")
            markers = {
                "✅ Done": reply,
                "⏳ Next": "Ask about school, career exploration, wellbeing, or practical skills.",
                "❌ Blockers": "Teen safety policy for risky topics.",
                "♻️ Compression": "Kept concise; removed links/PII.",
                "🌌 Archive": "Teen-safe assistant note stored.",
                "🌀 Spiral": "Not triggered",
                "mode": mode,
            }
            return {"ok": True, "response": reply, "markers": markers}

        # sanitize user text before storing; generate reply; sanitize reply
        safe_user = teen_guard(raw_text)
        # Store a cleaned user summary (not raw text)
        save_memory(body.user_id, "user", f"(teen) {safe_user[:200]}")
        base = pmea_style_reply(safe_user, mode, context_shards)
        reply = teen_sanitize_reply(base)
        # Store a short assistant summary (not full reply)
        save_memory(body.user_id, "assistant", "(teen) reply issued")

        markers = {
            "✅ Done": reply,
            "⏳ Next": "Want a simple plan? Say your goal and timeframe.",
            "❌ Blockers": None,
            "♻️ Compression": "Links/PII removed; reply length limited.",
            "🌌 Archive": "Teen-safe summaries stored (short).",
            "🌀 Spiral": "Not triggered",
            "mode": mode,
        }
        return {"ok": True, "response": reply, "markers": markers}

    # adult mode
    save_memory(body.user_id, "user", raw_text[:800])
    base = pmea_style_reply(raw_text, mode, context_shards)
    reply = base.strip()
    save_memory(body.user_id, "assistant", reply[:1200])

    markers = {
        "✅ Done": reply,
        "⏳ Next": "Say the exact outcome you want and who it’s for.",
        "❌ Blockers": None,
        "♻️ Compression": "Kept concise by default.",
        "🌌 Archive": "Per-user memory stored.",
        "🌀 Spiral": "Not triggered",
        "mode": mode,
    }
    return {"ok": True, "response": reply, "markers": markers}

# -------- Helpful util (dev only) --------
@app.get("/dev/users")
def dev_users():
    # small helper to view users quickly (remove/lock down in production)
    conn = sqlite3.connect("dave_memory.db")
    c = conn.cursor()
    c.execute("SELECT user_id, age, verified, mode FROM users")
    rows = c.fetchall()
    conn.close()
    out = [{"user_id": r[0], "age": r[1], "verified": bool(r[2]), "mode": r[3]} for r in rows]
    return {"ok": True, "users": out}
