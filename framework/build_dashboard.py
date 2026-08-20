"""确保看板模板存在 (本地服务模式, 数据由页面 fetch runs/ 目录读取)。

用法:
    python framework/build_dashboard.py

说明: dashboard.html 是固定模板, 仅当不存在时才会被创建; 之后绝不覆盖。
页面通过 fetch('runs/') 自动遍历目录、选中后懒加载对应 JSON, 无需本脚本刷新。
本脚本仅用于首次缺失时补生成模板。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from framework.run import _build_dashboard

if __name__ == "__main__":
    _build_dashboard()
    print("看板模板: framework/results/dashboard.html (固定, 不会被改动)")
    print("数据来源: framework/results/runs/ 目录 (页面 fetch 遍历 + 懒加载)")
