"""
Flask app for practising the AWS 3-tier architecture.

Stateless by default. Backends switch on via environment variables:
  - DB_HOST set    -> notes stored in RDS (PostgreSQL)
  - REDIS_HOST set -> sessions + notes cache in ElastiCache (Redis)
  - neither set    -> notes kept in memory on each instance (lost on restart,
                      and each instance has its own copy: a deliberate lesson)
"""
import json
import os

import requests
from flask import Flask, redirect, render_template_string, request, session

app = Flask(__name__)
# Must be the SAME on every instance, or cookie sessions break behind the ALB.
app.secret_key = os.environ.get("SECRET_KEY", "change-me")

DB_HOST = os.environ.get("DB_HOST")
REDIS_HOST = os.environ.get("REDIS_HOST")

# ---------- Optional: ElastiCache (Redis) ----------
cache = None
if REDIS_HOST:
    import redis
    from flask_session import Session

    cache = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)
    app.config["SESSION_TYPE"] = "redis"
    app.config["SESSION_REDIS"] = redis.Redis(host=REDIS_HOST, port=6379)
    Session(app)

CACHE_KEY = "notes:all"
CACHE_TTL = 30


# ---------- Optional: RDS (PostgreSQL) ----------
def db():
    import psycopg2

    return psycopg2.connect(
        host=DB_HOST,
        dbname=os.environ.get("DB_NAME", "notesdb"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
        connect_timeout=5,
    )


if DB_HOST:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS notes (
                   id SERIAL PRIMARY KEY, body TEXT NOT NULL,
                   created_by TEXT, created_at TIMESTAMP DEFAULT NOW())"""
        )

MEMORY_NOTES = []  # used when no DB is configured


# ---------- EC2 metadata (IMDSv2) ----------
def instance_info():
    try:
        token = requests.put(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
            timeout=1,
        )
        token.raise_for_status()
        token = token.text
        h = {"X-aws-ec2-metadata-token": token}
        base = "http://169.254.169.254/latest/meta-data/"
        r1 = requests.get(base + "instance-id", headers=h, timeout=1)
        r2 = requests.get(base + "placement/availability-zone", headers=h, timeout=1)
        r1.raise_for_status(); r2.raise_for_status()
        iid, az = r1.text, r2.text
        return iid, az
    except Exception:
        return "local", "local"


INSTANCE_ID, AZ = instance_info()


# ---------- Notes storage ----------
def load_notes():
    if not DB_HOST:
        return list(reversed(MEMORY_NOTES)), f"Memory on {INSTANCE_ID} only"
    if cache and (cached := cache.get(CACHE_KEY)):
        return json.loads(cached), "ElastiCache (cache hit)"
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT body, created_by FROM notes ORDER BY id DESC LIMIT 50")
        notes = [{"body": b, "created_by": c} for b, c in cur.fetchall()]
    if cache:
        cache.setex(CACHE_KEY, CACHE_TTL, json.dumps(notes))
    return notes, "RDS"


def save_note(body):
    who = f"{INSTANCE_ID} / {AZ}"
    if not DB_HOST:
        MEMORY_NOTES.append({"body": body, "created_by": who})
        return
    with db() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO notes (body, created_by) VALUES (%s, %s)", (body, who))
    if cache:
        cache.delete(CACHE_KEY)


# ---------- Routes ----------
PAGE = """
<!doctype html>
<title>3-Tier Notes</title>
<style>
 body{font-family:sans-serif;max-width:640px;margin:40px auto;padding:0 16px}
 .box{background:#f3f3f3;padding:12px;border-radius:6px;margin-bottom:16px}
 li{margin:4px 0}
</style>
<h1>3-Tier Notes</h1>
<div class="box">
  <b>Served by:</b> {{ iid }} in <b>{{ az }}</b><br>
  <b>Session store:</b> {{ sess }}<br>
  <b>Your visits this session:</b> {{ visits }}<br>
  <b>Notes source:</b> {{ notes_source }}
</div>
<form method="post" action="/notes">
  <input name="body" placeholder="Write a note" required style="width:75%">
  <button>Add</button>
</form>
<ul>
{% for n in notes %}<li>{{ n.body }} <small>(from {{ n.created_by }})</small></li>{% endfor %}
</ul>
"""


@app.route("/")
def index():
    session["visits"] = session.get("visits", 0) + 1
    notes, source = load_notes()
    return render_template_string(
        PAGE,
        iid=INSTANCE_ID,
        az=AZ,
        sess="ElastiCache (Redis)" if cache else "Signed browser cookie",
        visits=session["visits"],
        notes=notes,
        notes_source=source,
    )


@app.route("/notes", methods=["POST"])
def add_note():
    save_note(request.form["body"][:500])
    return redirect("/")


@app.route("/health")
def health():
    return {"status": "ok", "instance": INSTANCE_ID, "az": AZ}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)