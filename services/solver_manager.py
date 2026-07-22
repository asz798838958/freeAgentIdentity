"""Turnstile Solver 进程管理 - 后端启动时自动拉起"""
import subprocess
import sys
import os
import time
import threading
import signal
import requests

SOLVER_PORT = 8889
SOLVER_URL = f"http://localhost:{SOLVER_PORT}"
_proc: subprocess.Popen = None
_lock = threading.Lock()

# 连续启动失败计数，防止无限重试循环
_consecutive_failures = 0
_MAX_CONSECUTIVE_FAILURES = 3
_last_failure_reason = ""


def is_running() -> bool:
    try:
        r = requests.get(f"{SOLVER_URL}/", timeout=2)
        return r.status_code < 500
    except Exception:
        return False


def get_status() -> dict:
    """返回 solver 详细状态，供 API 使用。"""
    running = is_running()
    info: dict = {"running": running}
    if not running and _last_failure_reason:
        info["last_error"] = _last_failure_reason
    if not running and _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
        info["stopped_retrying"] = True
        info["message"] = f"连续 {_consecutive_failures} 次启动失败，已停止重试。请排查后手动重启。"
    return info


def _ensure_camoufox_browser() -> bool:
    """检查 Camoufox 浏览器二进制是否已下载，没装就自动 fetch。

    返回 True 表示就绪，False 表示下载失败（网络问题等）。Solver 启动前调用。
    首次下载约 100MB，之后会有缓存跳过。
    """
    try:
        from camoufox.pkgman import installed_verstr, CamoufoxNotInstalled
    except Exception as e:
        print(f"[Solver] camoufox 库导入失败: {e}")
        return False

    try:
        ver = installed_verstr()
        print(f"[Solver] Camoufox 浏览器已就绪 (v{ver})")
        return True
    except CamoufoxNotInstalled:
        pass
    except Exception as e:
        print(f"[Solver] Camoufox 浏览器检测异常，仍尝试安装: {e}")

    print("[Solver] Camoufox 浏览器未安装，开始下载（约 100MB，请耐心等待）...")
    try:
        from camoufox.pkgman import CamoufoxFetcher
        CamoufoxFetcher().install()
        print("[Solver] Camoufox 浏览器下载完成")
        return True
    except Exception as e:
        print(f"[Solver] Camoufox 浏览器下载失败: {e}")
        return False


def start():
    global _proc, _consecutive_failures, _last_failure_reason
    with _lock:
        if is_running():
            print("[Solver] 已在运行")
            _consecutive_failures = 0
            _last_failure_reason = ""
            return

        # 连续失败过多，拒绝再试（手动 restart 会重置计数器）
        if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            print(f"[Solver] 连续 {_consecutive_failures} 次启动失败，停止重试。请手动排查后重启。")
            return

        # 启动 Solver 子进程之前先确保 Camoufox 浏览器二进制可用
        if not _ensure_camoufox_browser():
            _consecutive_failures += 1
            _last_failure_reason = "Camoufox 浏览器不可用"
            print("[Solver] 由于 Camoufox 浏览器不可用，跳过 Solver 启动")
            return

        # PyInstaller 打包后 sys.executable 指向 backend 可执行文件，
        # 用 --solver 参数让它走 solver 入口；源码模式下走 python + start.py
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--solver",
                   "--browser_type", "camoufox",
                   "--thread", "1",
                   "--port", str(SOLVER_PORT)]
        else:
            solver_script = os.path.join(
                os.path.dirname(__file__), "turnstile_solver", "start.py"
            )
            cmd = [sys.executable, solver_script,
                   "--browser_type", "camoufox",
                   "--thread", "1",
                   "--port", str(SOLVER_PORT)]
        _proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        # 等待服务就绪（最多30s）
        for _ in range(30):
            time.sleep(1)
            if _proc.poll() is not None:
                # 子进程已退出，读取 stderr
                stderr_msg = ""
                try:
                    stderr_msg = _proc.stderr.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass
                _consecutive_failures += 1
                _last_failure_reason = stderr_msg or f"进程退出 code={_proc.returncode}"
                print(f"[Solver] 子进程异常退出 code={_proc.returncode} (连续失败 {_consecutive_failures}/{_MAX_CONSECUTIVE_FAILURES})")
                if stderr_msg:
                    print(f"[Solver] stderr: {stderr_msg}")
                _proc = None
                return
            if is_running():
                print(f"[Solver] 已启动 PID={_proc.pid}")
                _consecutive_failures = 0
                _last_failure_reason = ""
                # 关闭 stderr pipe 避免缓冲区满导致子进程阻塞
                try:
                    _proc.stderr.close()
                except Exception:
                    pass
                return
        # 启动超时
        _consecutive_failures += 1
        stderr_msg = ""
        if _proc and _proc.stderr:
            try:
                import select
                if select.select([_proc.stderr], [], [], 0)[0]:
                    stderr_msg = _proc.stderr.read(2000).decode("utf-8", errors="replace")
                _proc.stderr.close()
            except Exception:
                pass
        _last_failure_reason = f"启动超时 {stderr_msg}".strip()
        print(f"[Solver] 启动超时 (连续失败 {_consecutive_failures}/{_MAX_CONSECUTIVE_FAILURES})"
              f"{' stderr: ' + stderr_msg if stderr_msg else ''}")


def stop():
    global _proc
    with _lock:
        # 1. 先终止我们自己 spawn 的子进程
        if _proc and _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _proc.kill()
                _proc.wait(timeout=3)
            print("[Solver] 子进程已停止")
        _proc = None

        # 2. 即使 _proc 为空（Docker / 外部启动），也尝试通过端口查找残留进程并杀掉
        if is_running():
            _kill_by_port(SOLVER_PORT)
            for _ in range(10):
                time.sleep(0.5)
                if not is_running():
                    break
            if is_running():
                print("[Solver] 警告: 停止后端口仍被占用")
            else:
                print("[Solver] 残留进程已清理")


def _kill_by_port(port: int):
    """通过端口号查找并杀掉占用进程（跨平台）。"""
    import platform
    try:
        if platform.system() == "Windows":
            out = subprocess.check_output(
                ["netstat", "-ano", "-p", "TCP"], text=True, timeout=5
            )
            for line in out.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = int(parts[-1])
                    if pid > 0:
                        os.kill(pid, signal.SIGTERM)
        else:
            out = subprocess.check_output(
                ["lsof", "-ti", f":{port}"], text=True, timeout=5
            ).strip()
            for pid_str in out.splitlines():
                pid = int(pid_str.strip())
                if pid > 0 and pid != os.getpid():
                    os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def restart():
    """同步重启：stop → 等端口释放 → start。手动重启会重置失败计数器。"""
    global _consecutive_failures, _last_failure_reason
    _consecutive_failures = 0
    _last_failure_reason = ""
    stop()
    # 等端口完全释放，最多 5 秒
    for _ in range(10):
        if not is_running():
            break
        time.sleep(0.5)
    start()


def start_async():
    """在后台线程启动，不阻塞主进程"""
    t = threading.Thread(target=start, daemon=True)
    t.start()
