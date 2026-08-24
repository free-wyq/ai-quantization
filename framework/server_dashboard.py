"""一键启动本地看板服务 (动态注入 runs 数据)

用法:
    python framework/server_dashboard.py
浏览器打开: http://localhost:8000/framework/results/dashboard.html

设计要点 (尊重用户"不想动 dashboard.html"的诉求):
- 磁盘上的 framework/results/dashboard.html 始终保持原样, 绝不修改。
- 服务在响应 dashboard.html 请求时, 实时扫描 framework/results/runs/ 下的
  所有 JSON, 注入 window.__RUNS__ 列表 (replace 掉 <script src="runs/index.js">)。
- 因此每次刷新页面都会重新扫描 runs/, 自动显示最新回测记录,
  无需重新生成 HTML, 也无需前端遍历目录 (对 file:// 无效, 必须用本服务)。
- 同时保留原生静态文件能力: runs/ 下的 .json 与 klinecharts.min.js 均可直接访问。
"""
import os
import re
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(ROOT, "framework", "results")
RUNS_DIR = os.path.join(RESULTS_DIR, "runs")
PORT = 8000


def load_runs():
    """扫描 runs/ 目录, 读取全部 JSON, 按时间倒序 (最新在前)。"""
    runs = []
    if os.path.isdir(RUNS_DIR):
        for fn in os.listdir(RUNS_DIR):
            if fn.endswith(".json"):
                try:
                    runs.append(json.load(open(os.path.join(RUNS_DIR, fn),
                                                encoding="utf-8")))
                except Exception:
                    pass
    runs.sort(key=lambda r: r.get("id", ""), reverse=True)
    return runs


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.rstrip("/").endswith("dashboard.html"):
            return self._serve_dashboard()
        return super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

    def _serve_dashboard(self):
        fs_path = self.translate_path(self.path)
        if not os.path.isfile(fs_path):
            return super().do_GET()
        with open(fs_path, encoding="utf-8") as f:
            html = f.read()

        runs = load_runs()
        injection = ('<script>window.__RUNS__ = '
                     + json.dumps(runs, ensure_ascii=False) + ';</script>')

        # 优先替换 index.js 引用, 避免 404; 否则注入到 </head> 之前
        new_html, n = re.subn(
            r'<script src="runs/index\.js"></script>', injection, html, count=1)
        if n == 0:
            new_html = html.replace("</head>", injection + "\n</head>", 1)

        body = new_html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # 静默日志, 不打扰终端


if __name__ == "__main__":
    os.chdir(ROOT)
    print("=" * 60)
    print("  量化回测看板服务已启动")
    print("=" * 60)
    print(f"  打开: http://localhost:{PORT}/framework/results/dashboard.html")
    print("  说明: 每次刷新页面都会重新扫描 runs/, 自动显示最新回测。")
    print("        回测命令例: python framework/run.py macd 000001")
    print("  停止: Ctrl+C")
    print("=" * 60)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
