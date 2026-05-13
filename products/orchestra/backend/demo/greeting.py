from products.orchestra.backend.engine import ExecutionContext, execution, step


@step
async def build_greeting(name: str) -> str:
    return f"Hello, {name}!"


@step
async def log_greeting(greeting: str) -> None:
    print(f"[step log_greeting] {greeting}")


@execution
async def greeting_execution(ctx: ExecutionContext, name: str) -> str:
    greeting = await ctx.step(build_greeting, name)
    await ctx.sleep(2)
    await ctx.step(log_greeting, greeting)
    return greeting
