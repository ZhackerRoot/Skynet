from fastapi import FastAPI, Request
import psycopg2
import os
import requests
from datetime import datetime, timedelta
from fastapi import Header

app = FastAPI()

# =============================
# CONFIG
# =============================
DATABASE_URL = os.getenv("DATABASE_URL")
print("Database: ", DATABASE_URL)
ADMIN_KEY = os.getenv("ADMIN_KEY")
print("Admin_key: ", ADMIN_KEY)
BOT_KEY = os.getenv("BOT_KEY")
print("Bot_key: ", BOT_KEY)


TRIAL_DURATION = 3000  # 10 min


# =============================
# DATABASE CONNECTION
# =============================
def get_connection():
    return psycopg2.connect(DATABASE_URL)


# =============================
# HEALTH CHECK
# =============================
@app.get("/")
def health():
    return {"status": "server running"}


# =============================
# VERIFY USER (BOT START CHECK)
# =============================
@app.post("/verify")
def verify(data: dict):

    uid = data.get("uid")

    if not uid:
        return {"status": "invalid"}

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT plan,
               is_active,
               subscription_end,
               allow_demo,
               trial_start,
               trial_used
        FROM users
        WHERE uid=%s
    """, (uid,))

    row = cur.fetchone()

# ================= NEW USER AUTO CREATE =================
    if not row:

        trial_start = datetime.utcnow()

        cur.execute("""
            INSERT INTO users(
                uid,
                plan,
                is_active,
                allow_demo,
                trial_start,
                trial_used
            )
            VALUES(%s,'none',TRUE,FALSE,%s,FALSE)
        """,(uid, trial_start))

        conn.commit()

        cur.close()
        conn.close()

        return {
            "status": "trial",
            "remaining": TRIAL_DURATION
        }

    plan, is_active, sub_end, allow_demo, trial_start, trial_used = row
    now = datetime.utcnow()

    # =========================
    # BLOCKED USER
    # =========================
    if not is_active:
        cur.close()
        conn.close()
        return {"status": "blocked"}

    # =========================
    # PAID USERS (VIP/STANDARD/ADMIN)
    # =========================
    if plan in ["admin", "vip", "standard"]:

        # subscription expired
        if sub_end and sub_end < now:
            cur.close()
            conn.close()
            return {"status": "expired"}

        # 🔥 IMPORTANT: TRIAL DELETE
        cur.execute("""
            UPDATE users
            SET trial_start=NULL,
                trial_used=TRUE
            WHERE uid=%s
        """, (uid,))
        conn.commit()

        cur.close()
        conn.close()

        return {
            "status": "active",
            "plan": plan,
            "allow_demo": allow_demo
        }

    # =========================
    # TRIAL SYSTEM
    # =========================
    if plan == "none":

        # Trial already used → BLOCK
        if trial_used:
            cur.close()
            conn.close()
            return {"status": "trial_expired"}

        # Start trial once
        if not trial_start:
            trial_start = now
            cur.execute("""
                UPDATE users
                SET trial_start=%s
                WHERE uid=%s
            """, (trial_start, uid))
            conn.commit()

        elapsed = (now - trial_start).total_seconds()

        if elapsed > TRIAL_DURATION:

            cur.execute("""
                UPDATE users
                SET trial_used=TRUE
                WHERE uid=%s
            """, (uid,))
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

    return {"status": "invalid"}


# =============================
# HEARTBEAT (REALTIME CONTROL)
# Robot har 20s serverga uradi
# =============================
@app.post("/heartbeat")
def heartbeat(data: dict):

    uid = data.get("uid")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT plan,
               is_active,
               subscription_end,
               allow_demo
        FROM users
        WHERE uid=%s
    """, (uid,))

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return {"status": "not_found"}

    plan, is_active, sub_end, allow_demo = row
    now = datetime.utcnow()

    if not is_active:
        return {"status": "blocked"}

    if sub_end and sub_end < now:
        return {"status": "expired"}

    return {
        "status": "ok",
        "plan": plan,
        "allow_demo": allow_demo
    }

@app.post("/create_user_request")
def create_request(data: dict, x_bot_key: str = Header(None)):

    if x_bot_key != BOT_KEY:
        return {"status": "unauthorized"}

    uid = data["uid"]
    plan = data["plan"]
    payment_method = data.get("payment_method")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users(uid, plan, is_active, payment_method)
        VALUES(%s,'none',FALSE,%s)
        ON CONFLICT(uid)
        DO UPDATE SET payment_method=EXCLUDED.payment_method
    """,(uid, payment_method))

    conn.commit()
    cur.close()
    conn.close()

    return {"status":"ok"}

# Admin
@app.get("/admin/users")
def admin_users(x_admin_key: str = Header(None)):

    if x_admin_key != ADMIN_KEY:
        return {"error": "unauthorized"}

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            uid,
            plan,
            is_active,
            allow_demo,
            trial_start,
            trial_used,
            subscription_end
        FROM users
        ORDER BY trial_start DESC NULLS LAST
    """)

    rows = cur.fetchall()

    users = []

    for r in rows:
        users.append({
            "uid": r[0],
            "plan": r[1],
            "active": r[2],
            "allow_demo": r[3],
            "trial_start": str(r[4]),
            "trial_used": r[5],
            "subscription_end": str(r[6]),
        })

    cur.close()
    conn.close()

    return users

# Admin Vip
@app.post("/admin/vip")
def admin_vip(data: dict, x_admin_key: str = Header(None)):

    if x_admin_key != ADMIN_KEY:
        return {"error": "unauthorized"}

    uid = data["uid"]

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET plan='vip',
            is_active=TRUE,
            allow_demo=TRUE,
            subscription_end = NOW() + INTERVAL '30 days'
        WHERE uid=%s
    """,(uid,))

    conn.commit()
    cur.close()
    conn.close()

    return {"status":"vip_activated"}

# Admin Standard
@app.post("/admin/standard")
def admin_standard(data: dict, x_admin_key: str = Header(None)):

    if x_admin_key != ADMIN_KEY:
        return {"error": "unauthorized"}

    uid = data["uid"]

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET plan='standard',
            is_active=TRUE,
            allow_demo=FALSE,
            subscription_end = NOW() + INTERVAL '30 days'
        WHERE uid=%s
    """,(uid,))

    conn.commit()
    cur.close()
    conn.close()

    return {"status":"standard_activated"}

# Block User
@app.post("/admin/block")
def admin_block(data: dict, x_admin_key: str = Header(None)):

    if x_admin_key != ADMIN_KEY:
        return {"error": "unauthorized"}

    uid = data["uid"]

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET is_active=FALSE
        WHERE uid=%s
    """,(uid,))

    conn.commit()
    cur.close()
    conn.close()

    return {"status":"blocked"}

@app.post("/admin/delete")
def delete_user(data: dict, x_admin_key: str = Header(None)):

    if x_admin_key != ADMIN_KEY:
        return {"error": "unauthorized"}

    uid = data["uid"]

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM users WHERE uid=%s", (uid,))
    conn.commit()

    cur.close()
    conn.close()

    return {"status": "deleted"}

@app.post("/admin/cleanup")
def cleanup_users(x_admin_key: str = Header(None)):

    if x_admin_key != ADMIN_KEY:
        return {"error": "unauthorized"}

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM users
        WHERE
            plan='none'
            AND trial_used=TRUE
            AND subscription_end IS NULL
    """)

    deleted = cur.rowcount

    conn.commit()
    cur.close()
    conn.close()

    return {"deleted": deleted}
