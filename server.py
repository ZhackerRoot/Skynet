from fastapi import FastAPI
import psycopg2
import os
from datetime import datetime, timedelta

app = FastAPI()

TRIAL_DURATION = 600  # 10 min

DATABASE_URL = os.environ.get("DATABASE_URL")


print("DATABASE_URL VALUE:", os.getenv("DATABASE_URL"))


def get_connection():
    return psycopg2.connect(DATABASE_URL)


@app.get("/")
def health():
    return {"status": "server running"}

def create_admin():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (username, plan, allow_demo, is_active)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (username) DO NOTHING
    """, ("your_email_here", "admin", True, True))

    conn.commit()
    cur.close()
    conn.close()

create_admin()


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

    # BLOCKED
    if not is_active:
        return {"status": "blocked"}

    now = datetime.utcnow()

    # VIP / STANDARD / ADMIN
    if plan in ["vip", "standard", "admin"]:

        if sub_end and sub_end < now:
            return {"status": "expired"}

        return {
            "status": "active",
            "plan": plan,
            "allow_demo": allow_demo
        }

    # ===== TRIAL LOGIC =====
    if plan == "none":

        # Trial hali boshlanmagan
        if not trial_start:
            trial_start = now
            cur.execute("""
                UPDATE users
                SET trial_start=%s
                WHERE username=%s
            """, (trial_start, username))
            conn.commit()

        # Trial vaqt hisoblash
        elapsed = (now - trial_start).total_seconds()

        if elapsed > TRIAL_DURATION:
            cur.execute("""
                UPDATE users
                SET trial_used=TRUE
                WHERE username=%s
            """, (username,))
            conn.commit()

            return {"status": "trial_expired"}

        remaining = TRIAL_DURATION - elapsed

        return {
            "status": "trial",
            "remaining": int(remaining)
        }

    cur.close()
    conn.close()


