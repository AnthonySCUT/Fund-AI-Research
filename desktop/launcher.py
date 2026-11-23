from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


APP_NAME = "AI 基金智能投研"
SERVER_MODE = "--fund-ai-streamlit-server"


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def user_data_dir(environ: dict[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    base = values.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "FundAIResearch"


def choose_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def streamlit_argv(app_path: Path, port: int, secrets_path: Path) -> list[str]:
    args = [
        "streamlit",
        "run",
        str(app_path),
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ]
    if secrets_path.is_file():
        args.append(f"--secrets.files={secrets_path}")
    return args


def server_process_command(app_path: Path, port: int, secrets_path: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, SERVER_MODE, str(app_path), str(port), str(secrets_path)]
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        SERVER_MODE,
        str(app_path),
        str(port),
        str(secrets_path),
    ]


def run_server_mode(argv: list[str]) -> int:
    app_path = Path(argv[0])
    port = int(argv[1])
    secrets_path = Path(argv[2])
    sys.argv = streamlit_argv(app_path, port, secrets_path)
    from streamlit.web.cli import main

    main()
    return 0


def wait_for_server(url: str, process: subprocess.Popen, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("本地研究服务已退出，请查看 desktop.log。")
        try:
            with urlopen(f"{url}/_stcore/health", timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(0.25)
    raise TimeoutError("本地研究页面启动超时，请查看 desktop.log。")


def run_desktop() -> int:
    import webview

    root = resource_root()
    data_dir = user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "desktop.log"
    secrets_path = data_dir / "secrets.toml"
    app_path = root / "app.py"
    port = choose_port()
    url = f"http://127.0.0.1:{port}"

    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            server_process_command(app_path, port, secrets_path),
            cwd=data_dir,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            wait_for_server(url, process)
            webview.create_window(APP_NAME, url, width=1440, height=960, min_size=(1000, 700))
            webview.start(gui="edgechromium")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == SERVER_MODE:
        return run_server_mode(sys.argv[2:])
    try:
        return run_desktop()
    except Exception as exc:
        log_path = user_data_dir() / "desktop.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"Desktop startup failed: {type(exc).__name__}: {exc}\n")
        import tkinter as tk
        from tkinter import messagebox

        window = tk.Tk()
        window.withdraw()
        messagebox.showerror(APP_NAME, f"启动失败：{exc}\n\n日志：{log_path}")
        window.destroy()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
