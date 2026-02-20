from fastapi import FastAPI
import psycopg2
import os
from datetime import datetime

app = FastAPI()

TRIAL_DURATION = 600
DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    return psycopg2.connect(DATABASE_URL)

# ===============================
# CREATE ADMIN USER
# ===============================
def create_admin():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (username, plan, allow_demo, is_active)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (username) DO NOTHING
    """, ("zhackerline@gmail.com", "admin", True, True))

    conn.commit()
    cur.close()
    conn.close()


# App start paytida ishga tushadi
init_db()
create_admin()


@app.get("/")
def health():
    return {"status": "server running"}


# ===============================
# VERIFY ENDPOINT
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
               allow_demo, trial_start, trial_used
        FROM users
        WHERE username=%s
    """, (username,))

    row = cur.fetchone()

    if not row:
        cur.close()
        conn.close()
        return {"status": "not_found"}

    plan, is_active, sub_end, allow_demo, trial_start, trial_used = row
    now = datetime.utcnow()

    if not is_active:
        return {"status": "blocked"}

    # ===== PAID PLANS =====
    if plan in ["admin", "vip", "standard"]:

        if sub_end and sub_end < now:
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
            cur.execute("""
                UPDATE users SET trial_used=TRUE
                WHERE username=%s
            """, (username,))
            conn.commit()

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
