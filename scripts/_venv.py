"""共享的 venv 自举 —— quote.py / notices.py 共用。

用法（在脚本顶部、用到 akshare 之前）：
    from _venv import bootstrap
    bootstrap(__file__)

作用：当前解释器没装 akshare、但脚本同目录有 .venv 时，用 venv 的 python 重跑本脚本。
这样无论是否手动激活 venv，`python3 scripts/xxx.py ...` 都能直接用。
"""
import os
import sys


def bootstrap(script_path, sentinel="_AKSHARE_VENV_REEXEC"):
    """缺 akshare 且同目录有 .venv → 用 venv 的 python 重跑 script_path。

    用环境变量哨兵防死循环：venv 的 python 可能和系统 python3 是同一个二进制，
    只是 site-packages 不同（靠 pyvenv.cfg），所以不能用二进制路径判重，用哨兵。
    重跑过一次仍没有 akshare 就放手（让调用方给出友好的缺依赖提示）。
    """
    try:
        import akshare  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get(sentinel):
        return
    script_path = os.path.abspath(script_path)
    venv_py = os.path.join(os.path.dirname(script_path), ".venv", "bin", "python")
    if os.path.exists(venv_py):
        os.environ[sentinel] = "1"
        os.execv(venv_py, [venv_py, script_path, *sys.argv[1:]])
