from fastapi import FastAPI
import psycopg2
import os
from datetime import datetime

app = FastAPI()

DATABASE_URL = os.environ.get("DATABASE_URL")


print("DATABASE_URL VALUE:", os.getenv("DATABASE_URL"))


def get_connection():
    return psycopg2.connect(DATABASE_URL)


@app.get("/")
def health():
    return {"status": "server running"}


@app.post("/check_user")
def check_user(data: dict):
    username = data.get("username")

    if not username:
        return {"status": "invalid"}

    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT plan, is_active, subscription_end FROM users WHERE username=%s",
            (username,)
        )

        row = cur.fetchone()

        cur.close()
        conn.close()

        if not row:
            return {"status": "not_found"}

        plan, is_active, sub_end = row

        if not is_active:
            return {"status": "blocked"}

        if sub_end and sub_end < datetime.utcnow():
            return {"status": "expired"}

        return {"status": "active", "plan": plan}

    except Exception as e:
        return {"status": "error", "detail": str(e)}
