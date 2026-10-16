import time
import asyncio
from collections.abc import AsyncGenerator, Iterable

from .sandbox import ExecutionResult


class AsyncExecutionStream:
    def __init__(self, output: AsyncGenerator[str | ExecutionResult], timeout_seconds: int) -> None:
        self._output = output
        self._runner = asyncio.Runner()
        self._deadline = time.monotonic() + timeout_seconds
        self._result: ExecutionResult | None = None
        self._closed = False

    async def _next(self) -> str | ExecutionResult:
        async with asyncio.timeout(max(0, self._deadline - time.monotonic())):
            return await anext(self._output)

    def iter_stdout(self) -> Iterable[str]:
        while not self._closed and self._result is None:
            try:
                chunk = self._runner.run(self._next())
            except StopAsyncIteration:
                break
            if isinstance(chunk, ExecutionResult):
                self._result = chunk
            else:
                yield chunk

    def wait(self) -> ExecutionResult:
        for _ in self.iter_stdout():
            pass
        if self._result is None:
            raise RuntimeError("Sandbox execution ended without an exit status")
        return self._result

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._runner.run(self._output.aclose())
            finally:
                self._runner.close()
