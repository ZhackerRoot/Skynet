from fastapi import FastAPI
import psycopg2
import os
from datetime import datetime

app = FastAPI()

TRIAL_DURATION = 600
DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    return psycopg2.connect(DATABASE_URL)


@app.get("/")
def health():
    return {"status": "server running"}


# ===============================
# VERIFY (FIRST CHECK)
# ===============================
@app.post("/verify")
def verify(data: dict):

    username = data.get("username")

    if not username:
        return {"status": "invalid"}

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT plan, is_active, subscription_end,
               allow_demo, trial_start
        FROM users
        WHERE username=%s
    """, (username,))

    row = cur.fetchone()

    if not row:
        cur.close()
        conn.close()
        return {"status": "not_found"}

    plan, is_active, sub_end, allow_demo, trial_start = row
    now = datetime.utcnow()

    if not is_active:
        cur.close()
        conn.close()
        return {"status": "blocked"}

    # ===== PAID PLANS =====
    if plan in ["admin", "vip", "standard"]:

        if sub_end and sub_end < now:
            cur.close()
            conn.close()
            return {"status": "expired"}

        cur.close()
        conn.close()

        return {
            "status": "active",
            "plan": plan,
            "allow_demo": allow_demo
        }

    # ===== TRIAL =====
    if plan == "none":

        if not trial_start:
            trial_start = now
            cur.execute("""
                UPDATE users SET trial_start=%s
                WHERE username=%s
            """, (trial_start, username))
            conn.commit()

        elapsed = (now - trial_start).total_seconds()

        if elapsed > TRIAL_DURATION:
            cur.close()
            conn.close()
            return {"status": "trial_expired"}

        remaining = TRIAL_DURATION - elapsed

        cur.close()
        conn.close()

        return {
            "status": "trial",
            "remaining": int(remaining)
        }

    cur.close()
    conn.close()


# ===============================
# HEARTBEAT (REAL-TIME CHECK)
# ===============================
@app.post("/heartbeat")
def heartbeat(data: dict):

    username = data.get("username")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT is_active, subscription_end
        FROM users
        WHERE username=%s
    """, (username,))

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return {"status": "not_found"}

    is_active, sub_end = row
    now = datetime.utcnow()

    if not is_active:
        return {"status": "blocked"}

    if sub_end and sub_end < now:
        return {"status": "expired"}

    return {"status": "ok"}
