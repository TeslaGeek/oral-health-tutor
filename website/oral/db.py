import os

import certifi
import ssl
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker

load_dotenv()

DB_URL_RAW = os.getenv("DENTAL_DB_URL")
if not DB_URL_RAW:
    raise RuntimeError("DENTAL_DB_URL is not set in the environment.")

# Normalize URL and strip unsupported ssl-mode for PyMySQL; provide CA via connect_args.
url = make_url(DB_URL_RAW)
query = dict(url.query)

# Remove ssl-mode (MySQL client flag) and instead use ssl CA in connect_args
ssl_required = False
for key in ("ssl-mode", "ssl_mode"):
    if key in query:
        ssl_required = str(query.pop(key)).lower() in {"required", "true", "1", "yes"}

# Always ensure charset
query.setdefault("charset", "utf8mb4")

url = url.set(query=query)

connect_args = {}
if ssl_required or True:  # DO requires TLS; enforce with CA bundle.
    # For local dev, explicitly disable certificate verification to avoid self-signed chain errors.
    connect_args["ssl"] = {
        "cert_reqs": ssl.CERT_NONE,
        "check_hostname": False,
    }

engine = create_engine(url, echo=False, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine)


def ensure_session_schema():
    """Lightweight compatibility migration for additive columns."""
    try:
        inspector = inspect(engine)
        columns = {col.get("name") for col in inspector.get_columns("oral_sessions")}
        with engine.begin() as conn:
            if "test_justification" not in columns:
                conn.execute(text("ALTER TABLE oral_sessions ADD COLUMN test_justification TEXT NULL"))
    except Exception:
        # Keep startup resilient if DB metadata cannot be inspected at import time.
        pass


ensure_session_schema()
