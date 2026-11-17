# -*- coding: utf-8 -*-
"""
微尘 · 行为数据收集服务（零依赖，只用 Python 标准库）

启动：
    python collect.py            # 默认监听 0.0.0.0:8787
    python collect.py 9000       # 指定端口

工作方式：
    POST /events   body 为 JSON 数组或单个对象，每条就是前端 wc_track.js 产出的事件
                   返回 {"ok": true, "n": 收到的条数}
    GET  /health   返回已收集条数、今日条数
    GET  /dump     下载全部数据（application/x-ndjson）

落盘位置：同目录 data/events.jsonl（一行一条，可直接被 analyze.py 读取）
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
OUT = os.path.join(DATA_DIR, "events.jsonl")
os.makedirs(DATA_DIR, exist_ok=True)

# 部署时把这里改成你的站点域名；多个用逗号分隔；"*" 表示不限制（仅本地调试用）
ALLOW_ORIGIN = os.environ.get("WC_ALLOW_ORIGIN", "*")


def count_lines():
    if not os.path.exists(OUT):
        return 0
    with open(OUT, "rb") as f:
        return sum(1 for _ in f)


class Handler(BaseHTTPRequestHandler):
    server_version = "weichen-collect/1.0"

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
        path = self.path.split("?")[0]
        if path == "/health":
            n = count_lines()
            today = time.strftime("%Y-%m-%d")
            n_today = 0
            if os.path.exists(OUT):
                with open(OUT, "rb") as f:
                    for line in f:
                        try:
                            if json.loads(line.decode("utf-8")).get("day") == today:
                                n_today += 1
                        except Exception:
                            pass
            self._json({"ok": True, "total": n, "today": n_today})
        elif path == "/dump":
            if not os.path.exists(OUT):
                self._json({"ok": False, "msg": "no data yet"})
                return
            with open(OUT, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"ok": True, "msg": "weichen collector is running"}, 200)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/events", "/"):
            self._json({"ok": False, "msg": "unknown path"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list):
                raise ValueError("payload must be list or object")

            day = time.strftime("%Y-%m-%d")
            with open(OUT, "a", encoding="utf-8") as f:
                for e in data:
                    if isinstance(e, dict):
                        e.setdefault("day", day)
                        e.setdefault("recv", int(time.time() * 1000))
                        f.write(json.dumps(e, ensure_ascii=False) + "\n")
            self._json({"ok": True, "n": len(data)})
        except Exception as ex:
            self._json({"ok": False, "msg": str(ex)}, 400)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("微尘数据收集服务已启动：http://127.0.0.1:%d" % port)
    print("数据文件：%s" % OUT)
    print("已收集：%d 条" % count_lines())
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
