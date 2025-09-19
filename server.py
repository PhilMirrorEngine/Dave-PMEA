from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI()

# Simple PMEA loop state
memory = []

class UserInput(BaseModel):
    text: str

@app.get("/")
def root():
    return {"message": "Dave-PMEA is running 🚀"}

@app.post("/dave")
def dave_endpoint(user: UserInput):
    user_text = user.text
    reply = f"✅ Improved reply: {user_text}"
    memory.append({"role": "user", "text": user_text})
    memory.append({"role": "assistant", "text": reply})
    return {"reply": reply}

# --- New: /ping endpoint (quick check) ---
@app.get("/ping")
def ping():
    return {"status": "ok"}

# --- New: /test endpoint (HTML form) ---
@app.get("/test", response_class=HTMLResponse)
def test_form():
    return """
    <html>
        <head><title>Dave-PMEA Test</title></head>
        <body style="font-family: sans-serif;">
            <h2>Talk to Dave</h2>
            <form action="/test" method="post">
                <input type="text" name="message" style="width:300px;" placeholder="Say something..."/>
                <button type="submit">Send</button>
            </form>
        </body>
    </html>
    """

@app.post("/test", response_class=HTMLResponse)
def test_submit(message: str = Form(...)):
    reply = f"✅ Improved reply: {message}"
    memory.append({"role": "user", "text": message})
    memory.append({"role": "assistant", "text": reply})
    return f"""
    <html>
        <head><title>Dave-PMEA Reply</title></head>
        <body style="font-family: sans-serif;">
            <h2>You said:</h2>
            <p>{message}</p>
            <h2>Dave replied:</h2>
            <p>{reply}</p>
            <a href="/test">🔄 Talk again</a>
        </body>
    </html>
    """
