from __future__ import annotations

import os
import signal
import threading
import subprocess
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from types import FrameType


class Processes:
    def __init__(self, stack: ExitStack, root: Path, output: Path) -> None:
        self.stack = stack
        self.root = root
        self.output = output
        self.services: dict[str, subprocess.Popen[bytes]] = {}
        previous = signal.signal(signal.SIGTERM, self.interrupt)
        stack.callback(signal.signal, signal.SIGTERM, previous)

    @staticmethod
    def interrupt(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt("AI E2E runner terminated")

    @staticmethod
    def stop(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        finally:
            # A wrapper can exit before its descendants; kill the owned group as well.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)

    def start(
        self, name: str, command: list[str], env: dict[str, str], *, configuration: bytes | None = None
    ) -> subprocess.Popen[bytes]:
        log = self.stack.enter_context((self.output / f"{name}.log").open("wb"))
        process = subprocess.Popen(
            command,
            cwd=self.root,
            env=env,
            stdin=subprocess.PIPE if configuration is not None else subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.stack.callback(self.stop, process)
        self.services[name] = process
        if configuration is not None:
            assert process.stdin is not None
            process.stdin.write(configuration)
            process.stdin.close()
        return process

    def check(self) -> None:
        for name, process in self.services.items():
            if process.poll() is not None:
                raise RuntimeError(f"{name} exited unexpectedly ({process.returncode}); see {name}.log")

    def ready(self, probe: Callable[[], bool]) -> None:
        deadline = monotonic() + 60
        while monotonic() < deadline:
            self.check()
            if probe():
                return
            threading.Event().wait(0.1)
        raise TimeoutError("AI E2E service readiness exceeded 60 seconds")

    def ready_http(self, url: str) -> None:
        def probe() -> bool:
            try:
                return requests.get(url, timeout=1).status_code == 200
            except requests.RequestException:
                return False

        self.ready(probe)

    def run_browser(self, command: list[str], env: dict[str, str]) -> int:
        process = subprocess.Popen(command, cwd=self.root, env=env, start_new_session=True)
        try:
            while True:
                self.check()
                try:
                    return process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            self.stop(process)
