from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start(database: Path, port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env.update(
        {
            "PORT": str(port),
            "BIKESHED_DATABASE_URL": f"sqlite:///{database}",
            "BIKESHED_BASE_URL": f"http://127.0.0.1:{port}",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "app"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        if process.poll() is not None:
            output = process.stdout.read().decode() if process.stdout else ""
            pytest.fail(f"service exited during startup:\n{output}")
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=0.5)
            if response.status_code == 200:
                return process
        except httpx.HTTPError:
            time.sleep(0.15)
    process.terminate()
    pytest.fail("service did not become healthy")


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def test_the_app_runs_as_a_single_service_on_a_configurable_port(tmp_path):
    port = _free_port()
    database = tmp_path / "nested" / "bikeshed.db"
    process = _start(database, port)
    try:
        assert httpx.get(f"http://127.0.0.1:{port}/healthz").json() == {"status": "ok"}
        # the missing database directory is created on the mounted volume
        assert database.exists()
    finally:
        _stop(process)


def test_data_survives_a_service_restart(tmp_path):
    database = tmp_path / "data" / "bikeshed.db"
    port = _free_port()

    process = _start(database, port)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", follow_redirects=False) as client:
            registered = client.post(
                "/register",
                data={
                    "email": "ada@example.com",
                    "password": "correct horse battery",
                    "invite": "",
                },
            )
            assert registered.status_code == 303
    finally:
        _stop(process)

    # same mounted file, fresh process
    process = _start(database, port)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", follow_redirects=False) as client:
            logged_in = client.post(
                "/login",
                data={"email": "ada@example.com", "password": "correct horse battery"},
            )
            assert logged_in.status_code == 303
            assert client.get("/").status_code == 200
    finally:
        _stop(process)


def test_the_deployment_artifacts_exist():
    dockerfile = ROOT / "Dockerfile"
    assert dockerfile.exists()
    text = dockerfile.read_text()
    assert "VOLUME" in text
    assert '"python", "-m", "app"' in text
    assert 'BIKESHED_DATABASE_URL="sqlite:////data/bikeshed.db"' in text

    compose = (ROOT / "docker-compose.yml").read_text()
    assert "./data:/data" in compose
    assert "8000:8000" in compose
