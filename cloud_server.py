import os
import hashlib
from datetime import datetime
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

TURSO_URL = os.environ.get("TURSO_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")


def turso_execute(sql: str, args: list = None):
    """Envía consultas SQL directamente a Turso por HTTPS."""
    base_url = TURSO_URL.replace("libsql://", "https://").rstrip("/")
    endpoint = f"{base_url}/v2/pipeline"

    formatted_args = []
    for arg in (args or []):
        if isinstance(arg, int):
            formatted_args.append({"type": "integer", "value": str(arg)})
        else:
            formatted_args.append({"type": "text", "value": str(arg)})

    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": formatted_args}},
            {"type": "close"}
        ]
    }
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json"
    }

    resp = requests.post(endpoint, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    result = data["results"][0]
    if result["type"] == "error":
        raise Exception(result["error"]["message"])

    rows = []
    for row in result["response"]["result"].get("rows", []):
        rows.append([cell.get("value") for cell in row])
    return rows


def init_db():
    if not TURSO_URL or not TURSO_TOKEN:
        return
    try:
        turso_execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        turso_execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                content TEXT NOT NULL,
                pinches INTEGER DEFAULT 0,
                timestamp TEXT NOT NULL
            )
        """)
    except Exception as e:
        print("Error inicializando tablas:", e)


init_db()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


@app.route("/")
def health_check():
    return jsonify({
        "app": "CrabNet Cloud API",
        "status": "online",
        "time": datetime.now().isoformat()
    })


@app.route("/register", methods=["POST"])
def register():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if len(username) < 3 or not password:
        return jsonify({"error": "El usuario debe tener al menos 3 letras"}), 400
    try:
        turso_execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            [username, hash_password(password)]
        )
        return jsonify({"status": "ok"})
    except Exception:
        return jsonify({"error": "Ese nombre de usuario ya existe"}), 409


@app.route("/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    rows = turso_execute(
        "SELECT id FROM users WHERE username = ? AND password_hash = ?",
        [username, hash_password(password)]
    )
    if rows:
        return jsonify({"status": "ok", "username": username})
    return jsonify({"error": "Usuario o contraseña incorrectos"}), 401


@app.route("/feed", methods=["GET"])
def feed():
    rows = turso_execute(
        "SELECT id, username, content, pinches, timestamp FROM posts ORDER BY id DESC LIMIT 50"
    )
    posts = [
        {
            "id": int(row[0]),
            "username": row[1],
            "content": row[2],
            "pinches": int(row[3]),
            "timestamp": row[4]
        }
        for row in rows
    ]
    return jsonify(posts)


@app.route("/post", methods=["POST"])
def create_post():
    data = request.json or {}
    username = data.get("username", "").strip()
    content = data.get("content", "").strip()
    if not username or not content:
        return jsonify({"error": "El mensaje está vacío"}), 400
    now = datetime.now().strftime("%H:%M - %d/%m")
    turso_execute(
        "INSERT INTO posts (username, content, timestamp) VALUES (?, ?, ?)",
        [username, content, now]
    )
    return jsonify({"status": "ok"})


@app.route("/pinch/<int:post_id>", methods=["POST"])
def pinch(post_id):
    turso_execute("UPDATE posts SET pinches = pinches + 1 WHERE id = ?", [post_id])
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)