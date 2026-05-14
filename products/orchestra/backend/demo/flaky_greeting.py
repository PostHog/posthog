from pathlib import Path

from products.orchestra.backend.engine import ExecutionContext, execution, step

from .greeting import build_greeting

_MARKER = Path("/tmp/orchestra-flaky-greeting.attempted")  # noqa: S108


@step
async def flaky_log_greeting(greeting: str) -> str:
    if not _MARKER.exists():
        _MARKER.touch()
        raise ValueError("simulated transient failure on first attempt")
    print(f"[step flaky_log_greeting] {greeting}")  # noqa: T201
    return f"logged: {greeting}"


@execution
async def flaky_greeting_execution(ctx: ExecutionContext, name: str) -> str:
    greeting = await ctx.step(build_greeting, name)
    await ctx.step(flaky_log_greeting, greeting)
    return greeting
