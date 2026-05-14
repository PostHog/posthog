import asyncio
from pathlib import Path

try:
    from orchestra_engine import ExecutionContext, execution, step
except ImportError:
    from products.orchestra.backend.engine import ExecutionContext, execution, step


_MARKER = Path("/tmp/orchestra-flaky-greeting.attempted")  # noqa: S108


def simulate_failure() -> None:
    if not _MARKER.exists():
        _MARKER.touch()
        raise ValueError("oh oh")


@step
async def build_greeting(name: str) -> str:
    await asyncio.sleep(2)
    return f"Hello, {name}!"


@step
async def flaky_log_greeting(greeting: str) -> str:
    await asyncio.sleep(2)
    simulate_failure()
    print(f"[step flaky_log_greeting] {greeting}")  # noqa: T201
    _MARKER.unlink(missing_ok=True)
    return f"logged: {greeting}"


@execution
async def flaky_greeting_execution(ctx: ExecutionContext, name: str) -> str:
    greeting = await ctx.step(build_greeting, name)
    await ctx.step(flaky_log_greeting, greeting)
    return greeting
