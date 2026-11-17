# -*- coding: utf-8 -*-
"""
微尘 · 实验数据后端（零依赖：Python 标准库 http.server + sqlite3）

为什么不用 Flask：你这台机器没装 Flask，装了也要 pip 联网。
这个文件 API 与 Flask 版完全一致，随时可换。启动：

    python app.py              # 监听 0.0.0.0:8787
    python app.py 9000         # 指定端口

库文件：同目录 wc.db（sqlite，可用 DB Browser 直接打开看）

接口
----
POST /api/events       前端 wc_track.js 批量上报（数组）。自动拆进 trials / events / assessments
POST /api/participants {"pid":"WC001","arm":"A","age_band":"18-22"}
POST /api/assess       {"pid":"WC001","arm":"A","y":12,"s":9,"level_y":"轻","level_s":"稳定"}
GET  /api/health       {"ok":true,"n_events":..,"by_arm":{"A":..,"B":..},"n_participants":..}
GET  /api/export       全库 JSON（调试/备份用）

设计要点
--------
* 只存行为：题目键、反应时、改答次数、质量标记、焦虑值、字数。不存任何文本原文、不存姓名学号。
* 幂等：网页重试/重复上报不会产生重复 trial（用 sid+seq 去重）。
* 时间：保留前端毫秒时间戳 t（epoch），另存 day 便于按日聚合。
"""
import json
import os
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "wc.db")
ALLOW_ORIGIN = os.environ.get("WC_ALLOW_ORIGIN", "*")

SCHEMA = """
CREATE TABLE IF NOT EXISTS participants (
  pid         TEXT PRIMARY KEY,
  arm         TEXT,
  age_band    TEXT,
  created_at  TEXT,
  first_ts    INTEGER,
  last_ts     INTEGER,
  n_sessions  INTEGER DEFAULT 0,
  n_items     INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trials (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  pid       TEXT,
  arm       TEXT,
  page      TEXT,
  item_key  TEXT,
  ts        INTEGER,
  rt_ms     INTEGER,
  rev       INTEGER,
  quality   TEXT,
  hid_ms    INTEGER,
  day       TEXT,
  dedup     TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_trials_pid ON trials(pid);
CREATE TABLE IF NOT EXISTS events (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  pid     TEXT,
  arm     TEXT,
  type    TEXT,
  ts      INTEGER,
  day     TEXT,
  payload TEXT,
  dedup   TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_events_pid ON events(pid);
CREATE TABLE IF NOT EXISTS assessments (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  pid       TEXT,
  arm       TEXT,
  phase     TEXT,
  y         INTEGER,
  s         INTEGER,
  level_y   TEXT,
  level_s   TEXT,
  ts        INTEGER,
  day       TEXT
);
"""


def today_str(ts=None):
    return time.strftime("%Y-%m-%d", time.localtime((ts or time.time() * 1000) / 1000.0)) if ts and ts > 1e12 \
        else time.strftime("%Y-%m-%d")


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)


def upsert_participant(conn, pid, arm, age_band, ts=None):
    if not pid:
        return
    ts = ts or int(time.time() * 1000)
    row = conn.execute("SELECT pid FROM participants WHERE pid=?", (pid,)).fetchone()
    if row:
        conn.execute("UPDATE participants SET arm=COALESCE(NULLIF(?, ''), arm), "
                     "age_band=COALESCE(NULLIF(?, ''), age_band), last_ts=MAX(COALESCE(last_ts,0), ?) "
                     "WHERE pid=?", (arm or "", age_band or "", ts, pid))
    else:
        conn.execute("INSERT INTO participants(pid,arm,age_band,created_at,first_ts,last_ts,n_sessions,n_items) "
                     "VALUES(?,?,?,?,?,?,0,0)",
                     (pid, arm or "", age_band or "", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts / 1000.0)),
                      ts, ts))


def ingest_event(conn, e):
    """把一条 wc 事件落到对应表；返回是否写入 trials"""
    if not isinstance(e, dict):
        return
    pid = e.get("pid") or ""
    arm = (e.get("arm") or "").upper()
    page = e.get("pg") or ""
    typ = e.get("e") or ""
    ts = int(e.get("t") or time.time() * 1000)
    day = e.get("day") or time.strftime("%Y-%m-%d", time.localtime(ts / 1000.0))
    dedup = "%s:%s:%s:%s" % (e.get("sid", ""), e.get("seq", ""), page, typ)
    x = e.get("x") or {}

    if typ == "page_view":
        upsert_participant(conn, pid, arm, x.get("ageBand", ""), ts)
        return

    if typ == "register_submit":
        upsert_participant(conn, pid, arm, x.get("ageBand", ""), ts)

    if typ == "item_answer":
        # 关键实验变量：单题反应时 + 是否重答
        try:
            conn.execute(
                "INSERT INTO trials(pid,arm,page,item_key,ts,rt_ms,rev,quality,hid_ms,day,dedup) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (pid, arm, page, x.get("key", ""), ts, int(x.get("rtMs") or 0),
                 1 if int(x.get("rev") or 1) == 1 else 0, e.get("q", "ok"),
                 int(x.get("hm") or 0), day, dedup))
        except sqlite3.IntegrityError:
            return
        conn.execute("UPDATE participants SET n_items=COALESCE(n_items,0)+1, last_ts=? WHERE pid=?", (ts, pid))
        return

    if typ == "assess_final":
        # 同一 pid 第一次 = 前测，第二次起 = 后测；30 分钟内重复上报（页面重复触发）直接丢弃
        last = conn.execute("SELECT phase,y,s,ts FROM assessments WHERE pid=? ORDER BY id DESC LIMIT 1",
                            (pid,)).fetchone()
        if last and abs(ts - (last["ts"] or 0)) < 30 * 60 * 1000 and last["y"] == x.get("y") and last["s"] == x.get("s"):
            return
        n = conn.execute("SELECT COUNT(*) c FROM assessments WHERE pid=?", (pid,)).fetchone()["c"]
        phase = "pre" if n == 0 else "post"
        conn.execute("INSERT INTO assessments(pid,arm,phase,y,s,level_y,level_s,ts,day) "
                     "VALUES(?,?,?,?,?,?,?,?,?)",
                     (pid, arm, phase, x.get("y"), x.get("s"), x.get("levelY", ""), x.get("levelS", ""), ts, day))

    try:
        conn.execute("INSERT INTO events(pid,arm,type,ts,day,payload,dedup) VALUES(?,?,?,?,?,?,?)",
                     (pid, arm, typ, ts, day, json.dumps(x, ensure_ascii=False), dedup))
    except sqlite3.IntegrityError:
        return
    if typ == "session_complete":
        conn.execute("UPDATE participants SET n_sessions=COALESCE(n_sessions,0)+1, last_ts=? WHERE pid=?", (ts, pid))
    upsert_participant(conn, pid, arm, "", ts)


class Handler(BaseHTTPRequestHandler):
    server_version = "weichen-api/1.0"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", ALLOW_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        with db() as conn:
            if path in ("/api/health", "/health"):
                by_arm = {}
                for r in conn.execute("SELECT arm, COUNT(*) c FROM participants").fetchall():
                    by_arm[r["arm"] or "-"] = r["c"]
                self._json({
                    "ok": True,
                    "n_participants": conn.execute("SELECT COUNT(*) c FROM participants").fetchone()["c"],
                    "n_trials": conn.execute("SELECT COUNT(*) c FROM trials").fetchone()["c"],
                    "n_events": conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"],
                    "n_assessments": conn.execute("SELECT COUNT(*) c FROM assessments").fetchone()["c"],
                    "n_sessions": conn.execute("SELECT COALESCE(SUM(n_sessions),0) c FROM participants").fetchone()["c"],
                    "by_arm": by_arm,
                    "db": DB_PATH,
                })
            elif path in ("/api/export", "/dump"):
                data = {t: [dict(r) for r in conn.execute("SELECT * FROM %s" % t).fetchall()]
                        for t in ("participants", "trials", "events", "assessments")}
                self._json({"ok": True, "data": data})
            else:
                self._json({"ok": True, "msg": "weichen api running", "db": DB_PATH})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception as ex:
            self._json({"ok": False, "msg": "bad json: %s" % ex}, 400)
            return

        if path in ("/api/events", "/events", "/"):
            items = payload if isinstance(payload, list) else [payload]
            with db() as conn:
                for e in items:
                    ingest_event(conn, e)
            self._json({"ok": True, "n": len(items)})
            return

        if path in ("/api/participants", "/api/assess"):
            with db() as conn:
                upsert_participant(conn, payload.get("pid"), payload.get("arm"), payload.get("age_band"))
                if path.endswith("assess"):
                    n2 = conn.execute("SELECT COUNT(*) c FROM assessments WHERE pid=?",
                                      (payload.get("pid"),)).fetchone()["c"]
                    conn.execute("INSERT INTO assessments(pid,arm,phase,y,s,level_y,level_s,ts,day) "
                                 "VALUES(?,?,?,?,?,?,?,?,?)",
                                 (payload.get("pid"), payload.get("arm"), "pre" if n2 == 0 else "post",
                                  payload.get("y"), payload.get("s"),
                                  payload.get("level_y", ""), payload.get("level_s", ""),
                                  int(time.time() * 1000), today_str()))
            self._json({"ok": True})
            return

        self._json({"ok": False, "msg": "unknown path"}, 404)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    init_db()
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("微尘实验后端已启动： http://127.0.0.1:%d" % port)
    print("数据库： %s" % DB_PATH)
    print("前端 wc_track.js 里 endpoint 填： http://<本机IP>:%d/api/events" % port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
