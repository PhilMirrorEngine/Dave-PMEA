from fastapi import FastAPI, Body
from pydantic import BaseModel
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.openapi.utils import get_openapi
import sqlite3, time, json
from datetime import datetime

app = FastAPI(title="Dave-PMEA", description="PMEA demo API", version="1.0.0")

# ── DB bootstrap ────────────────────────────────────────────────────────────────
DB = "dave_memory.db"

def run_db(sql, params=(), fetch=False, many=False):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    try:
        if many:
            cur.executemany(sql, params)
        else:
            cur.execute(sql, params)
        if fetch:
            rows = cur.fetchall()
        else:
            rows = None
        conn.commit()
        return rows
    finally:
        conn.close()

def init_db():
    run_db("""
    CREATE TABLE IF NOT EXISTS users (
      user_id     TEXT PRIMARY KEY,
      name        TEXT,
      dob         TEXT,       -- YYYY-MM-DD
      memory_name TEXT,
      created_at  TEXT
    )
    """)
    run_db("""
    CREATE TABLE IF NOT EXISTS memory (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id   TEXT,
      role      TEXT,
      text      TEXT,
      timestamp TEXT
    )
    """)

init_db()

# ── Models ─────────────────────────────────────────────────────────────────────
class SetupIn(BaseModel):
    user_id: str
    name: str
    dob: str            # expect YYYY-MM-DD
    memory_name: str

class ChatIn(BaseModel):
    user: str           # user_id
    message: str
    dob: str | None = None   # optional (will be ignored if user already set up)

# ── Tiny PMEA reply (placeholder) ───────────────────────────────────────────────
def pmea_reply(user_text: str) -> str:
    # Minimal “revise” step.
    return f"Improved reply: {user_text}"

# ── Helpers ────────────────────────────────────────────────────────────────────
def user_profile(user_id: str):
    rows = run_db("SELECT user_id,name,dob,memory_name FROM users WHERE user_id=?",
                  (user_id,), fetch=True)
    if not rows:
        return None
    uid, name, dob, mem = rows[0]
    ok = bool(uid and name and dob and mem)
    return {"user_id": uid, "name": name, "dob": dob, "memory_name": mem, "complete": ok}

def save_turn(user_id: str, role: str, text: str):
    run_db("INSERT INTO memory (user_id,role,text,timestamp) VALUES (?,?,?,?)",
           (user_id, role, text, datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")))

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <h3>✅ Dave-PMEA is running.</h3>
    <ul>
      <li>GET <code>/ping</code></li>
      <li>POST <code>/setup</code> (user_id, name, dob, memory_name)</li>
      <li>POST <code>/chat</code>  (gated until setup)</li>
      <li>GET <code>/memory?limit=20</code></li>
      <li>GET <code>/openapi.json</code></li>
    </ul>
    """

@app.get("/ping")
def ping():
    return {"ok": True}

@app.post("/setup")
def setup(payload: SetupIn):
    # Basic DOB sanity: YYYY-MM-DD
    try:
        datetime.strptime(payload.dob, "%Y-%m-%d")
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "DOB must be YYYY-MM-DD"}
        )
    exists = user_profile(payload.user_id)
    if exists is None:
        run_db(
            "INSERT INTO users (user_id,name,dob,memory_name,created_at) VALUES (?,?,?,?,?)",
            (payload.user_id, payload.name, payload.dob, payload.memory_name,
             datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
        )
    else:
        run_db(
            "UPDATE users SET name=?, dob=?, memory_name=? WHERE user_id=?",
            (payload.name, payload.dob, payload.memory_name, payload.user_id)
        )
    return {"ok": True, "user": payload.user_id}

@app.get("/memory")
def get_memory(user_id: str | None = None, limit: int = 20):
    if user_id:
        rows = run_db("SELECT role,text,timestamp FROM memory WHERE user_id=? ORDER BY id DESC LIMIT ?",
                      (user_id, limit), fetch=True)
    else:
        rows = run_db("SELECT role,text,timestamp FROM memory ORDER BY id DESC LIMIT ?",
                      (limit,), fetch=True)
    out = [{"role": r[0], "text": r[1], "timestamp": r[2]} for r in rows]
    return {"ok": True, "items": out}

@app.post("/chat")
def chat(payload: ChatIn):
    """
    Gate: if user profile is missing/incomplete, refuse “chat” and ask
    for: name, dob (YYYY-MM-DD), memory_name.
    """
    uid = payload.user.strip()
    prof = user_profile(uid)

    if (prof is None) or (prof and not prof["complete"]):
        # Hard gate until setup is complete
        ask = {
            "need_profile": True,
            "message": (
                "Before we chat, please provide your profile.\n"
                "Reply (or call /setup) with JSON:\n"
                '{ "user_id": "<your-id>", "name": "<Your Name>", '
                '"dob": "YYYY-MM-DD", "memory_name": "<Memory Label>" }'
            ),
            "missing": {
                "has_user": bool(prof),
                "has_name": bool(prof and prof["name"]),
                "has_dob": bool(prof and prof["dob"]),
                "has_memory_name": bool(prof and prof["memory_name"])
            }
        }
        return JSONResponse(status_code=412, content=ask)

    # Profile OK → process message
    user_text = payload.message
    save_turn(uid, "user", user_text)
    reply = pmea_reply(user_text)
    save_turn(uid, "assistant", reply)
    return {"reply": reply, "profile": {"user_id": prof["user_id"], "name": prof["name"], "memory_name": prof["memory_name"]}}

# ── OpenAPI “servers” fix (so GPT Builder can import by URL) ───────────────────
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
        description=app.description
    )
    schema["servers"] = [{"url": "https://dave-pmea.onrender.com"}]  # update if your URL differs
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi
