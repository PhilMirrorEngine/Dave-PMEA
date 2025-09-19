# server.py  — Dave-PMEA minimal API with SQLite memory
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Any
import sqlite3
from contextlib import closing
from pathlib import Path

# ---------- App ----------
app = FastAPI(title="Dave-PMEA", description="PMEA demo API", version="1.0.0")

# ---------- SQLite (simple, file in working dir) ----------
DB_PATH = Path("dave_memory.db")

def init_db() -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                t   DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_t ON memory(t DESC)")
        conn.commit()

def save_memory(role: str, text: str) -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("INSERT INTO memory(role, text) VALUES (?, ?)", (role, text))
        conn.commit()

def read_memory(limit: int = 20) -> List[Dict[str, Any]]:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, role, text, t FROM memory ORDER BY t DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

# Make sure DB exists on startup
init_db()

# ---------- Models ----------
class UserInput(BaseModel):
    text: str

# ---------- Routes ----------
@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "message": "Dave-PMEA is running",
        "endpoints": {
            "GET /ping": "health check",
            "POST /dave": "talk to Dave (body: {'text': 'hello'})",
            "GET /memory": "last 20 stored lines",
        },
    }

@app.get("/ping")
def ping() -> Dict[str, str]:
    return {"status": "ok"}

@app.post("/dave")
def dave(user: UserInput) -> Dict[str, str]:
    # store user turn
    save_memory("user", user.text)

    # --- PMEA placeholder: DRAFT -> CRITIQUE -> REVISE (simplified) ---
    # For now we just return a concise, improved echo.
    reply = f"Improved reply: {user.text}"

    # store assistant turn
    save_memory("assistant", reply)

    return {"reply": reply}

@app.get("/memory")
def memory() -> Dict[str, Any]:
    return {"items": read_memory(limit=20)}

# ---------- OpenAPI servers fix (so GPT Builder import-from-URL works) ----------
from fastapi.openapi.utils import get_openapi
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
        description=app.description,
    )
    # Update this URL if your Render URL is different
    schema["servers"] = [{"url": "https://dave-pmea.onrender.com"}]
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi
