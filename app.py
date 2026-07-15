import eventlet
eventlet.monkey_patch()

import os
import random
import sqlite3
import string
from datetime import datetime, timezone

from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, join_room, emit

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=3 * 1024 * 1024)

DB_PATH = os.path.join(os.path.dirname(__file__), "chat.db")

# In-memory tracking of who's connected to each room, so we can cap rooms at
# 2 people. This resets on server restart, which is fine for a simple
# 1-on-1 chat app.
room_sessions = {}  # room_code -> {sid: username}

# Characters chosen to avoid visually ambiguous ones (0/O, 1/I/l).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room TEXT NOT NULL,
            username TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            msg_type TEXT NOT NULL DEFAULT 'text',
            reply_to_id INTEGER,
            reply_username TEXT,
            reply_snippet TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rooms (
            code TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        )
        """
    )
    # Migrations for databases created before these columns existed.
    for stmt in (
        "ALTER TABLE messages ADD COLUMN msg_type TEXT NOT NULL DEFAULT 'text'",
        "ALTER TABLE messages ADD COLUMN reply_to_id INTEGER",
        "ALTER TABLE messages ADD COLUMN reply_username TEXT",
        "ALTER TABLE messages ADD COLUMN reply_snippet TEXT",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def generate_room_code(length=6):
    conn = get_db()
    while True:
        code = "".join(random.choice(CODE_ALPHABET) for _ in range(length))
        exists = conn.execute("SELECT 1 FROM rooms WHERE code = ?", (code,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO rooms (code, created_at) VALUES (?, ?)",
                (code, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            conn.close()
            return code


def room_code_exists(code):
    conn = get_db()
    row = conn.execute("SELECT 1 FROM rooms WHERE code = ?", (code,)).fetchone()
    conn.close()
    return bool(row)


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        action = request.form.get("action")
        username = request.form.get("username", "").strip()

        if not username:
            return render_template("index.html", error="Please enter your name.", active_tab=action or "create")

        if action == "create":
            code = generate_room_code()
            session["username"] = username
            session["room"] = code
            return redirect(url_for("chat"))

        elif action == "join":
            code = request.form.get("room", "").strip().upper()
            if not code:
                return render_template("index.html", error="Please enter a room code.", active_tab="join")
            if not room_code_exists(code):
                return render_template(
                    "index.html",
                    error="That room code doesn't exist. Double check it, or create a new room instead.",
                    active_tab="join",
                )
            session["username"] = username
            session["room"] = code
            return redirect(url_for("chat"))

        return render_template("index.html", error="Something went wrong. Please try again.")

    return render_template("index.html")


@app.route("/chat")
def chat():
    if "username" not in session or "room" not in session:
        return redirect(url_for("index"))

    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, username, message, timestamp, msg_type,
               reply_to_id, reply_username, reply_snippet
        FROM messages WHERE room = ? ORDER BY id ASC
        """,
        (session["room"],),
    ).fetchall()
    conn.close()

    history = [dict(row) for row in rows]
    return render_template(
        "chat.html",
        username=session["username"],
        room=session["room"],
        history=history,
    )


@app.route("/leave")
def leave():
    session.clear()
    return redirect(url_for("index"))


@socketio.on("join")
def handle_join(data):
    room = data["room"]
    username = data["username"]
    sid = request.sid

    members = room_sessions.setdefault(room, {})
    distinct_usernames = set(members.values())

    if username not in distinct_usernames and len(distinct_usernames) >= 2:
        emit("room_full", {}, room=sid)
        return

    members[sid] = username
    join_room(room)
    emit(
        "status",
        {"msg": f"{username} has joined the chat."},
        room=room,
    )


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    for room, members in list(room_sessions.items()):
        if sid in members:
            username = members.pop(sid)
            emit("status", {"msg": f"{username} has left the chat."}, room=room)
            if not members:
                del room_sessions[room]


@socketio.on("message")
def handle_message(data):
    room = data["room"]
    username = data["username"]
    message = data["message"].strip()
    msg_type = data.get("type", "text")
    if msg_type not in ("text", "sticker", "image"):
        msg_type = "text"
    if not message:
        return

    # Basic safety cap on image sticker payload size (already resized client-side).
    if msg_type == "image" and len(message) > 2_000_000:
        return

    reply_to_id = data.get("reply_to_id")
    reply_username = data.get("reply_username")
    reply_snippet = data.get("reply_snippet")
    if reply_snippet:
        reply_snippet = reply_snippet[:120]

    timestamp = datetime.now(timezone.utc).strftime("%H:%M")

    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO messages
            (room, username, message, timestamp, msg_type, reply_to_id, reply_username, reply_snippet)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (room, username, message, timestamp, msg_type, reply_to_id, reply_username, reply_snippet),
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()

    emit(
        "message",
        {
            "id": new_id,
            "username": username,
            "message": message,
            "timestamp": timestamp,
            "type": msg_type,
            "reply_to_id": reply_to_id,
            "reply_username": reply_username,
            "reply_snippet": reply_snippet,
        },
        room=room,
    )


@socketio.on("seen")
def handle_seen(data):
    room = data["room"]
    username = data["username"]
    last_id = data.get("last_id")
    # Relay to everyone else in the room so senders know their messages were seen.
    emit(
        "seen",
        {"username": username, "last_id": last_id},
        room=room,
        include_self=False,
    )


@socketio.on("typing")
def handle_typing(data):
    emit(
        "typing",
        {"username": data["username"]},
        room=data["room"],
        include_self=False,
    )


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=True)
