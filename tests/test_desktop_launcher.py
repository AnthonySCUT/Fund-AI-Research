from pathlib import Path

from desktop.launcher import choose_port, streamlit_argv, user_data_dir


def test_user_data_dir_uses_local_appdata():
    assert user_data_dir({"LOCALAPPDATA": r"C:\Users\Tester\AppData\Local"}) == Path(
        r"C:\Users\Tester\AppData\Local\FundAIResearch"
    )


def test_streamlit_argv_includes_local_secrets_when_present(tmp_path):
    app = tmp_path / "app.py"
    secrets = tmp_path / "secrets.toml"
    secrets.write_text('DEEPSEEK_API_KEY = "test"', encoding="utf-8")

    args = streamlit_argv(app, 8517, secrets)

    assert str(app) in args
    assert "--server.address=127.0.0.1" in args
    assert "--server.port=8517" in args
    assert f"--secrets.files={secrets}" in args


def test_choose_port_returns_a_local_bindable_port():
    port = choose_port()
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))
