# server.py  — Dave-PMEA API (clean reset)
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
from fastapi.responses import HTMLResponse
from fastapi.openapi.utils import get_openapi
import sqlite3
from datetime import datetime

# ------------------ App ------------------
app = FastAPI(title="Dave-PMEA", version="1.0.0", description="PMEA demo API")

# ------------------ DB (auto-create) ------------------
DB_PATH = "dave_memory.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        text TEXT,
        ts DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

def save_memory(role: str, text: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO memory(role, text) VALUES(?, ?)", (role, text))
    conn.commit()
    conn.close()

def read_memory(limit: int = 20):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT role, text, ts FROM memory ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [{"role": r, "text": t, "ts": ts} for (r, t, ts) in rows]

init_db()

# ------------------ Models ------------------
class UserInput(BaseModel):
    text: str

# ------------------ Routes ------------------
@app.get("/ping")
def ping():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <html>
      <head><title>Dave-PMEA</title></head>
      <body style="font-family:sans-serif">
        <p>✅ Dave-PMEA is running.</p>
        <ul>
          <li>GET <code>/ping</code></li>
          <li>POST <code>/dave</code>  (body: {"text":"hello"})</li>
          <li>GET <code>/memory</code></li>
        </ul>
      </body>
    </html>
    """

@app.post("/dave")
def dave_endpoint(user: UserInput):
    # minimal PMEA-style echo
    user_text = user.text.strip()
    reply = f"Improved reply: {user_text}\nTip: next, tell me the exact task and target output."
    save_memory("user", user_text)
    save_memory("assistant", reply)
    return {
        "reply": reply,
        "✅ Done": "Drafted, critiqued, revised (minimal).",
        "⏳ Next": "Give me your exact task + target output.",
        "❌ Blockers": None,
        "♻️ Compression": "Not needed",
    }

@app.get("/memory")
def memory_endpoint():
    return {"items": read_memory(20)}

# ------------------ OpenAPI `servers` fix ------------------
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
        description=app.description,
    )
    # 🔧 SET THIS TO YOUR RENDER URL EXACTLY
    schema["servers"] = [{"url": "https://dave-pmea.onrender.com"}]
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi
