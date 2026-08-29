"""策略包: 自动发现所有 Strategy 子类并注册到 STRATS

用户只需在 custom/ 目录下新建 .py 文件定义 Strategy 子类，
框架启动时自动扫描并注册，无需修改任何框架代码。
"""

import importlib
import pkgutil
import inspect

from .base import Strategy

STRATS = {}


def _discover():
    """扫描本包及子包下所有模块，收集 Strategy 子类"""
    for _, modname, _ in pkgutil.walk_packages(__path__, prefix=__name__ + "."):
        try:
            mod = importlib.import_module(modname)
        except Exception as e:
            print(f"  [警告] 策略模块加载失败 {modname}: {e}")
            continue
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, Strategy) and obj is not Strategy and obj.__module__ == modname:
                STRATS[obj.name] = obj


_discover()
