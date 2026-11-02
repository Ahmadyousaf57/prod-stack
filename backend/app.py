import logging
import os
import threading
from contextlib import contextmanager
from datetime import date

import psycopg2
from flask import Flask, jsonify, request
from psycopg2.errors import ForeignKeyViolation, UniqueViolation
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.url_map.strict_slashes = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prod-stack")

SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS bookings (
    id SERIAL PRIMARY KEY,
    resource_id INTEGER NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    booked_by TEXT NOT NULL,
    booking_date DATE NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (resource_id, booking_date)
);
"""

SAMPLE_RESOURCES = [
    ("Meeting Room A", "Seats 8, projector and whiteboard"),
    ("Lab PC 01", "Workstation with Docker installed"),
    ("Camera Kit", "DSLR with tripod"),
]

_schema_ready = False
_schema_lock = threading.Lock()


def get_conn():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


@contextmanager
def db():
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with db() as cur:
            cur.execute(SCHEMA)
            cur.execute("SELECT count(*) AS n FROM resources")
            if cur.fetchone()["n"] == 0:
                for name, description in SAMPLE_RESOURCES:
                    cur.execute(
                        "INSERT INTO resources (name, description) VALUES (%s, %s)",
                        (name, description),
                    )
        _schema_ready = True
        log.info("database schema is ready")


def clean(value, limit):
    return str(value or "").strip()[:limit]


@app.before_request
def prepare():
    if request.path.startswith("/health"):
        return None
    try:
        ensure_schema()
    except psycopg2.OperationalError as exc:
        log.error("database not reachable: %s", exc)
        return jsonify(error="database not reachable"), 503
    return None


@app.after_request
def log_request(resp):
    if not request.path.startswith("/health"):
        log.info("%s %s -> %s", request.method, request.path, resp.status_code)
    return resp


@app.errorhandler(500)
def server_error(_exc):
    return jsonify(error="internal server error"), 500


@app.route("/health")
def health():
    return "ok", 200


@app.route("/data/")
def data():
    with db() as cur:
        cur.execute("SELECT version() AS v")
        version = cur.fetchone()["v"]
    return jsonify(db_version=version)


@app.route("/stats")
def stats():
    with db() as cur:
        cur.execute(
            """
            SELECT
              (SELECT count(*) FROM resources) AS resources,
              (SELECT count(*) FROM bookings) AS bookings,
              (SELECT count(*) FROM bookings WHERE booking_date >= CURRENT_DATE) AS upcoming
            """
        )
        return jsonify(cur.fetchone())


@app.route("/resources")
def list_resources():
    with db() as cur:
        cur.execute("SELECT id, name, description FROM resources ORDER BY name")
        return jsonify(cur.fetchall())


@app.route("/resources", methods=["POST"])
def add_resource():
    body = request.get_json(silent=True) or {}
    name = clean(body.get("name"), 100)
    description = clean(body.get("description"), 300)
    if not name:
        return jsonify(error="name is required"), 400
    try:
        with db() as cur:
            cur.execute(
                "INSERT INTO resources (name, description) VALUES (%s, %s) "
                "RETURNING id, name, description",
                (name, description),
            )
            row = cur.fetchone()
    except UniqueViolation:
        return jsonify(error="a resource with this name already exists"), 409
    return jsonify(row), 201


@app.route("/resources/<int:resource_id>", methods=["DELETE"])
def delete_resource(resource_id):
    with db() as cur:
        cur.execute("DELETE FROM resources WHERE id = %s", (resource_id,))
        deleted = cur.rowcount
    if not deleted:
        return jsonify(error="resource not found"), 404
    return jsonify(deleted=resource_id)


@app.route("/bookings")
def list_bookings():
    resource_id = request.args.get("resource_id", type=int)
    query = """
        SELECT b.id, b.resource_id, r.name AS resource, b.booked_by,
               to_char(b.booking_date, 'YYYY-MM-DD') AS booking_date, b.note
        FROM bookings b JOIN resources r ON r.id = b.resource_id
    """
    params = ()
    if resource_id is not None:
        query += " WHERE b.resource_id = %s"
        params = (resource_id,)
    query += " ORDER BY b.booking_date, r.name"
    with db() as cur:
        cur.execute(query, params)
        return jsonify(cur.fetchall())


@app.route("/bookings", methods=["POST"])
def add_booking():
    body = request.get_json(silent=True) or {}
    resource_id = body.get("resource_id")
    booked_by = clean(body.get("booked_by"), 100)
    note = clean(body.get("note"), 300)
    try:
        day = date.fromisoformat(str(body.get("booking_date", "")))
    except ValueError:
        return jsonify(error="booking_date must be YYYY-MM-DD"), 400
    if not isinstance(resource_id, int) or isinstance(resource_id, bool):
        return jsonify(error="resource_id must be a number"), 400
    if not booked_by:
        return jsonify(error="booked_by is required"), 400
    if day < date.today():
        return jsonify(error="booking_date is in the past"), 400
    try:
        with db() as cur:
            cur.execute(
                "INSERT INTO bookings (resource_id, booked_by, booking_date, note) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (resource_id, booked_by, day, note),
            )
            new_id = cur.fetchone()["id"]
    except UniqueViolation:
        return jsonify(error="this resource is already booked on that date"), 409
    except ForeignKeyViolation:
        return jsonify(error="resource not found"), 404
    return jsonify(id=new_id), 201


@app.route("/bookings/<int:booking_id>", methods=["DELETE"])
def delete_booking(booking_id):
    with db() as cur:
        cur.execute("DELETE FROM bookings WHERE id = %s", (booking_id,))
        deleted = cur.rowcount
    if not deleted:
        return jsonify(error="booking not found"), 404
    return jsonify(deleted=booking_id)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
