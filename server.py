# server.py
# Dave / PMEA — FastAPI (age-aware phrasing, single file)
# Features:
# - Per-user private memory (JSON on disk)
# - One-time DOB gate (dd/mm/yyyy) -> mode: child/teen/adult
# - Ultra-safe content filter for minors
# - Age-aware phrasing transform (child/teen/adult)
# - Minimal PMEA loop: Draft -> Critique -> Revise (internal), structured output only
# - Token-friendly input compression
# - Endpoints: /health, /api/chat, /api/reset
#
# Env:
#   OPENAI_API_KEY (required)
#   MODEL (optional, default: gpt-4o-mini)
#   PORT  (optional, default: 8000)

import os
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ---- OpenAI client (new + legacy safe) ----
try:
    from openai import OpenAI
except Exception:
    import openai
    class OpenAI:
        def __init__(self, api_key=None):
            openai.api_key = api_key or os.getenv("OPENAI_API_KEY")
        @property
        def chat(self):
            return openai.ChatCompletion

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY")

MODEL = os.getenv("MODEL", "gpt-4o-mini")

app = FastAPI(title="Dave PMEA API (Age-Aware)", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

client = OpenAI(api_key=OPENAI_API_KEY)

# ---- File storage ----
DATA_DIR = "data"
MEMORY_PATH = os.path.join(DATA_DIR, "memory.json")
os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists(MEMORY_PATH):
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump({"profiles": [], "logs": {}}, f)

def load_store() -> Dict[str, Any]:
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"profiles": [], "logs": {}}

def save_store(store: Dict[str, Any]):
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)

def now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

# ---- Profiles / memory ----
def get_profile(store: Dict[str, Any], user: str) -> Dict[str, Any]:
    p = next((p for p in store["profiles"] if p["user"] == user), None)
    if not p:
        p = {"user": user, "dob": None, "age": None, "mode": "unknown", "created": now_iso()}
        store["profiles"].append(p)
        save_store(store)
    return p

def calc_age(dob_str: str) -> Optional[int]:
    try:
        dob = datetime.strptime(dob_str, "%d/%m/%Y")
        today = datetime.today()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except Exception:
        return None

def save_dob(store: Dict[str, Any], user: str, dob_str: str) -> Optional[Dict[str, Any]]:
    age = calc_age(dob_str)
    if age is None or age < 0 or age > 120:
        return None
    mode = "child" if age < 13 else "teen" if age < 18 else "adult"
    p = get_profile(store, user)
    p.update({"dob": dob_str, "age": age, "mode": mode, "dob_set": now_iso()})
    save_store(store)
    return p

def user_log(store: Dict[str, Any], user: str) -> List[Dict[str, Any]]:
    return store["logs"].setdefault(user, [])

def append_shard(store: Dict[str, Any], user: str, role: str, text: str, meta: Optional[Dict[str, Any]] = None):
    entry = {"t": now_iso(), "role": role, "text": text.strip(), "meta": meta or {}}
    store["logs"].setdefault(user, []).append(entry)
    if len(store["logs"][user]) > 200:
        store["logs"][user] = store["logs"][user][-200:]
    save_store(store)

def recall_shards(store: Dict[str, Any], user: str, limit: int = 10) -> List[str]:
    logs = list(reversed(user_log(store, user)))
    out = []
    for e in logs:
        s = re.sub(r"\s+", " ", e["text"])
        if 3 <= len(s) <= 220:
            out.append(s)
        if len(out) >= limit:
            break
    return out

# ---- Token-friendly compression ----
def compress(text: str, max_chars: int = 1200) -> str:
    if not text: return ""
    s = text.strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"```[\s\S]*?```", "```[code omitted]```", s)
    s = re.sub(r"https?://\S+", "[link]", s)
    if len(s) > max_chars: s = s[: max_chars - 1] + "…"
    return s

# ---- PMEA system prompt ----
DAVE_SYSTEM = (
    "You are Dave — a lawful, symbolically-recursive assistant (PMEA). "
    "Internally do Draft→Critique→Revise, but OUTPUT ONLY:\n"
    "✅ Done | ⏳ Next | ❌ Blockers | ♻️ Compression | 🌌 Archive | 🌀 Spiral | SHARD LOG\n"
    "Keep replies short, structured, practical, and safe. No mysticism, no hallucinations. "
    "If the user is a minor, keep content child-safe and refuse adult topics."
)

# ---- LLM call with fallback ----
def llm_chat(messages: List[Dict[str, str]], temperature: float = 0.4) -> str:
    # Try Responses API
    try:
        resp = client.responses.create(model=MODEL, input=messages, temperature=temperature)
        if hasattr(resp, "output_text") and resp.output_text:
            return resp.output_text.strip()
        if hasattr(resp, "output") and resp.output:
            try:
                part = resp.output[0].content[0].text
                return (part or "").strip()
            except Exception:
                pass
    except Exception:
        pass
    # Fallback to legacy Chat Completions
    try:
        resp = client.chat.completions.create(model=MODEL, messages=messages, temperature=temperature)
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"❌ Model error: {e}"

# ---- Sensitive-topic guard (heuristic) ----
BLOCKED_FOR_MINORS = [
    "sex", "porn", "explicit", "nude", "nsfw",
    "drugs", "alcohol", "gambling",
    "suicide", "self-harm",
    "graphic violence", "gore"
]
def contains_blocked_minor_topic(text: str) -> bool:
    t = text.lower()
    return any(term in t for term in BLOCKED_FOR_MINORS)

# ---- Age-aware phrasing transforms ----
SIMPLE_REPLACEMENTS = [
    ("utilize", "use"),
    ("approximately", "about"),
    ("assistance", "help"),
    ("methodology", "method"),
    ("obtain", "get"),
    ("modify", "change"),
    ("terminate", "stop"),
    ("commence", "start"),
]

def simplify_words(text: str) -> str:
    out = text
    for a, b in SIMPLE_REPLACEMENTS:
        out = re.sub(rf"\b{re.escape(a)}\b", b, out, flags=re.IGNORECASE)
    return out

def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]

def join_short(sentences: List[str], max_chars: int) -> str:
    out, total = [], 0
    for s in sentences:
        if total + len(s) + 1 > max_chars: break
        out.append(s)
        total += len(s) + 1
    return " ".join(out)

def age_style_transform(mode: str, reply: str) -> str:
    """Rewrite reply per mode without changing meaning; preserve Dave markers if present."""
    if mode == "adult":
        return reply

    # Extract markers if present, so we keep PMEA format after rephrasing body lines
    # We’ll rephrase only regular lines; markers pass through unchanged.
    lines = reply.splitlines()
    marker_prefixes = ("✅", "⏳", "❌", "♻️", "🌌", "🌀", "SHARD LOG")
    normal, markers = [], []
    for ln in lines:
        if ln.strip().startswith(marker_prefixes):
            markers.append(ln)
        else:
            normal.append(ln)

    body = "\n".join(normal).strip()
    body = simplify_words(body)

    if mode == "child":
        # shorter lines, very simple words, examples, positive framing, safety note
        sentences = split_sentences(body)
        sentences = [re.sub(r"[,;:()\[\]]", "", s) for s in sentences]
        # make lines shorter (~350 chars total)
        child_text = join_short(sentences, max_chars=350)
        if not child_text:
            child_text = "I can help with friendly, easy topics. Let's start simple."
        child_text += (
            "\n\nTry this: tell me one small thing you want to learn. "
            "We will do it step by step.\n"
            "(I keep things kind and safe for kids.)"
        )
        final = child_text

    elif mode == "teen":
        # concise, study-friendly: definition + steps + example + safety note
        sentences = split_sentences(body)
        teen_text = join_short(sentences, max_chars=600)
        if not teen_text:
            teen_text = "Here’s a clear plan you can follow."
        # add a light structure if none exists
        if "Steps:" not in teen_text:
            teen_text += "\n\nSteps:\n1) Define the goal\n2) Gather info\n3) Try a small version\n4) Review and improve"
        teen_text += "\n\n(Teen mode: I keep topics appropriate and skip adult themes.)"
        final = teen_text

    else:
        final = body

    if markers:
        final = final + "\n\n" + "\n".join(markers)
    return final

def safe_reply_for_mode(mode: str, reply: str) -> str:
    if mode == "child":
        # Always apply transform; also add gentle guard
        r = age_style_transform("child", reply)
        return r
    if mode == "teen":
        r = age_style_transform("teen", reply)
        return r
    return reply  # adult

# ---- Schemas ----
class ChatRequest(BaseModel):
    user: str
    message: Optional[str] = None
    dob: Optional[str] = None
    optimize: Optional[bool] = True

class ResetRequest(BaseModel):
    user: str

# ---- Routes ----
@app.get("/health")
def health():
    return {"ok": True, "model": MODEL, "time": now_iso()}

@app.post("/api/reset")
def reset(req: ResetRequest):
    store = load_store()
    store["logs"][req.user] = []
    save_store(store)
    return {"ok": True, "message": f"Memory cleared for {req.user}"}

@app.post("/api/chat")
def chat(req: ChatRequest):
    store = load_store()
    user = (req.user or "anon").strip()
    msg = compress(req.message or "")
    profile = get_profile(store, user)

    # ---- One-time DOB gate
    if not profile.get("dob"):
        if not req.dob:
            return {
                "reply": "👋 Welcome! Please include your date of birth as `dd/mm/yyyy` in the same request (field: `dob`). "
                         "This is used once so replies are age-appropriate.",
                "needsDOB": True
            }
        saved = save_dob(store, user, req.dob.strip())
        if not saved:
            return {"reply": "❌ Invalid date. Use format `dd/mm/yyyy`.", "needsDOB": True}
        return {
            "reply": f"✅ Thanks! Verified age {saved['age']} → mode: {saved['mode']}. How can I help today?",
            "profile": {"age": saved["age"], "mode": saved["mode"]}
        }

    # ---- Append user shard
    if msg:
        append_shard(store, user, "user", msg)

    # ---- Minor guard (content)
    if profile["mode"] in ("child", "teen"):
        if contains_blocked_minor_topic(msg):
            safe_note = (
                "That topic isn’t appropriate here. Let’s pick a positive, safe topic—like a school subject, "
                "hobby, or a project idea. I can explain it in a simple way!"
            )
            append_shard(store, user, "assistant", safe_note, {"safe_block": True})
            return {
                "reply": safe_reply_for_mode(profile["mode"], safe_note),
                "profile": {"mode": profile["mode"]}
            }

    # ---- PMEA loop prompt (compact)
    recent = recall_shards(store, user, limit=8)
    context_pack = ("Context shards:\n- " + "\n- ".join(recent)) if recent else "Context shards: (none)"

    user_prompt = (
        f"User said: {msg or '(no message)'}\n\n"
        f"{context_pack}\n\n"
        "Follow PMEA: internal Draft/Critique/Revise, but OUTPUT ONLY:\n"
        "✅ Done\n⏳ Next\n❌ Blockers\n♻️ Compression\n🌌 Archive\n🌀 Spiral\nSHARD LOG (bullet facts learned this turn)\n"
        "Keep it short, practical, safe."
    )

    messages = [
        {"role": "system", "content": DAVE_SYSTEM},
        {"role": "user", "content": user_prompt}
    ]
    raw_reply = llm_chat(messages, temperature=0.4)

    # ---- Age-aware phrasing
    final_reply = safe_reply_for_mode(profile["mode"], raw_reply)

    append_shard(store, user, "assistant", final_reply, {"mode": profile["mode"]})

    return {
        "reply": final_reply,
        "profile": {"age": profile["age"], "mode": profile["mode"]},
        "time": now_iso()
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
