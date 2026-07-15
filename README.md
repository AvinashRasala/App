# PyChat — Simple 1-on-1 Chat App (Python)

A real-time 1-on-1 chat app built with Flask + Flask-SocketIO. Two people join
the same "room code" and chat privately, in real time, with message history
saved in SQLite.

## Run it locally

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000 in two different browser tabs (or two
devices), use the same room code in both, and start chatting.

## Deploy for free — Render.com

Render's free tier needs no credit card and supports WebSockets, which this
app needs for real-time chat.

1. Push this folder to a new GitHub repository.
2. Go to https://render.com and sign up / log in (you can use GitHub login).
3. Click **New +** → **Web Service**.
4. Connect your GitHub repo.
5. Fill in the settings:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn -k eventlet -w 1 app:app`
   - **Instance Type**: Free
6. Click **Create Web Service**. Render will build and deploy automatically.
7. Once live, Render gives you a URL like `https://your-app.onrender.com` —
   share that with the person you want to chat with.

Notes on the free tier:
- The service "sleeps" after ~15 minutes of no traffic and takes ~30-60
  seconds to wake up on the next visit — normal for free hosting.
- SQLite data resets on redeploys (Render's free disk isn't persistent).
  Fine for a simple chat app; if you need permanent history, swap in a
  managed database like Render's free Postgres later.

## Alternative: Railway.app

Same steps as above — Railway also auto-detects Python/Flask apps, supports
WebSockets, and has a free trial tier. Just set the same start command.

## Project structure

```
chatapp/
├── app.py              # Flask + SocketIO backend
├── requirements.txt     # Python dependencies
├── Procfile             # Tells Render/Railway how to start the app
├── templates/
│   ├── index.html       # Join screen (name + room code)
│   └── chat.html        # Chat room UI
└── static/
    └── style.css        # Styling
```

## How it works

- Enter your name and a room code (any string) on the join screen.
- Share that exact same room code with the other person.
- Both of you land in the same private chat room and see messages instantly
  via WebSockets (Socket.IO).
- Messages are stored in `chat.db` (SQLite) so refreshing the page keeps
  your chat history.
