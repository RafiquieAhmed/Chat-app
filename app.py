from flask import Flask, render_template, request, redirect, url_for
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
import os
import sqlite3
import datetime

app = Flask(__name__)

# ---- CONFIG ----
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise RuntimeError("GOOGLE_API_KEY is not set in .env")

# Use a valid Gemini model id
llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash-001",   # <- key change from gemini-1.5-flash
    google_api_key=GOOGLE_API_KEY,
)

DB_FILE = "chatbot.db"


# ---- DB HELPERS ----
def get_db_connection():
    # Same connection helper everywhere
    return sqlite3.connect(DB_FILE, timeout=10, check_same_thread=False)


def init_db():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                created_at TEXT
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                sender TEXT,
                text TEXT,
                created_at TEXT,
                FOREIGN KEY(chat_id) REFERENCES chats(id)
            )
            """
        )
        conn.commit()


init_db()


# ---- ROUTES ----
@app.route("/")
def home():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, title FROM chats ORDER BY created_at DESC")
        chats = c.fetchall()

    if chats:
        # Redirect to most recent chat
        return redirect(url_for("view_chat", chat_id=chats[0][0]))
    else:
        # Create first chat
        return redirect(url_for("new_chat"))


@app.route("/chat/<int:chat_id>")
def view_chat(chat_id):
    with get_db_connection() as conn:
        c = conn.cursor()

        # All chats for sidebar
        c.execute("SELECT id, title FROM chats ORDER BY created_at DESC")
        all_chats = c.fetchall()

        # Check if requested chat exists
        c.execute("SELECT id FROM chats WHERE id = ?", (chat_id,))
        row = c.fetchone()
        if row is None:
            # If chat doesn't exist, go to home
            return redirect(url_for("home"))

        # Messages for this chat
        c.execute(
            "SELECT sender, text FROM messages WHERE chat_id=? ORDER BY created_at ASC",
            (chat_id,),
        )
        chat_history = [{"sender": r[0], "text": r[1]} for r in c.fetchall()]

    return render_template(
        "index.html",
        chats=all_chats,
        chat_history=chat_history,
        current_chat=chat_id,
    )


@app.route("/new_chat")
def new_chat():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_db_connection() as conn:
        c = conn.cursor()

        # Create new chat
        c.execute(
            "INSERT INTO chats (title, created_at) VALUES (?, ?)",
            (f"Chat {now}", now),
        )
        chat_id = c.lastrowid

        # Initial AI message
        c.execute(
            "INSERT INTO messages (chat_id, sender, text, created_at) VALUES (?, ?, ?, ?)",
            (chat_id, "ai", "Hello! How can I help you today?", now),
        )

        conn.commit()

    return redirect(url_for("view_chat", chat_id=chat_id))


@app.route("/send/<int:chat_id>", methods=["POST"])
def send_message(chat_id):
    user_message = request.form.get("message", "").strip()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if user_message:
        # 1. Store user message
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO messages (chat_id, sender, text, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, "user", user_message, now),
            )
            conn.commit()

        # 2. Build prompt
        prompt = f"""
        You are a friendly, polite, and helpful AI assistant for general conversation.
        Always respond respectfully and to the point.
        Limit your answer to two sentences.
        If the query is unclear, politely ask for clarification.

        User: {user_message}
        """

        # 3. Call AI with error handling
        try:
            ai_response = llm.invoke(prompt)
            # In most recent LangChain, .content is a string; str(...) is safe fallback
            ai_reply = (
                ai_response.content
                if isinstance(ai_response.content, str)
                else str(ai_response.content)
            )
            ai_reply = ai_reply.strip()
        except Exception as e:
            # Log error to console and show friendly message to user
            print("Gemini error:", repr(e))
            ai_reply = "Sorry, I'm having trouble connecting to the AI service right now."

        # 4. Store AI response
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO messages (chat_id, sender, text, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, "ai", ai_reply, now),
            )
            conn.commit()

    return redirect(url_for("view_chat", chat_id=chat_id))


if __name__ == "__main__":
    # For local dev only; in production use a proper WSGI server
    app.run(debug=True)
