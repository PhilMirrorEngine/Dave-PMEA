from fastapi import FastAPI
from pydantic import BaseModel
import sqlite3
from datetime import datetime
from fastapi.openapi.utils import get_openapi

app = FastAPI()

# --- DB setup (SQLite) ---
def init_db():
    conn = sqlite3.connect("dave_memory.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        text TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

def save_memory(role: str, text: str):
    conn = sqlite3.connect("dave_memory.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO memory (role, text) VALUES (?, ?)", (role, text))
    conn.commit()
    conn.close()

def get_memory(limit: int = 20):
    conn = sqlite3.connect("dave_memory.db")
    cursor = conn.cursor()
    cursor.execute("SELECT role, text, timestamp FROM memory ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [{"role": r, "text": t, "timestamp": ts} for r, t, ts in rows]

init_db()

# --- Data model for chat input ---
class UserInput(BaseModel):
    text: str

# --- Endpoints ---
@app.get("/")
def root():
    return {"message": "Dave-PMEA is running 🚀"}

@app.get("/ping")
def ping():
    return {"status": "ok"}

@app.post("/dave")
def dave_endpoint(user: UserInput):
    user_text = user.text
    reply = f"Improved reply: {user_text}"
    save_memory("user", user_text)
    save_memory("assistant", reply)
    return {"reply": reply}

@app.get("/memory")
def memory_endpoint():
    return get_memory()

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/api/chat")
def chat(message: str):
    reply = f"Improved reply: {message}"
    save_memory("user", message)
    save_memory("assistant", reply)
    return {"reply": reply}

# --- OpenAPI fix (adds servers entry) ---
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title="Dave-PMEA",
        version="1.0.0",
        routes=app.routes,
        description="OpenAPI for Dave-PMEA"
    )
    schema["servers"] = [{"url": "https://dave-pmea.onrender.com"}]
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi
