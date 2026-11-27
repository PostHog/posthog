"""Group self-reported model names into families such as "Claude Sonnet" or "GPT-6"."""

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from products.mcp_analytics.backend.hogql_queries.dashboard_query import MODEL_LABEL_SQL

UNKNOWN_FAMILY = "Unknown"
OTHER_FAMILY = "Other"

# First match wins, so a specific family sits above the generic pattern that would also match it:
# "gpt-oss" before "gpt", "codex" before "gpt-5". Agents type most model names themselves and get the
# version wrong far more often than the family, so a family never names a version below the major one.
MODEL_FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("GPT-OSS", "gpt-oss"),
    ("Claude Opus", "opus"),
    ("Claude Sonnet", "sonnet"),
    ("Claude Haiku", "haiku"),
    ("Claude Fable", "fable"),
    ("Claude", "claude"),
    ("Codex", "codex"),
    ("GPT-6", "gpt-6"),
    ("GPT-5", "gpt-5"),
    ("GPT-4", "gpt-4"),
    ("OpenAI o-series", "(?:^|[^a-z0-9_])o[1-9]"),
    ("GPT", "gpt"),
    ("Gemini", "gemini"),
    ("Gemma", "gemma"),
    ("Grok", "grok"),
    ("DeepSeek", "deepseek"),
    ("Qwen", "qwen"),
    ("Llama", "llama"),
    ("Kimi", "kimi"),
    ("GLM", "glm"),
    ("Mistral", "mistral|devstral|codestral"),
    ("MiniMax", "minimax"),
    ("Composer", "composer"),
)


def model_family_expr() -> ast.Expr:
    model = parse_expr(MODEL_LABEL_SQL)
    args: list[ast.Expr] = [
        parse_expr("{model} = 'Unknown'", placeholders={"model": model}),
        ast.Constant(value=UNKNOWN_FAMILY),
    ]
    for family, pattern in MODEL_FAMILY_PATTERNS:
        lowered_model = ast.Call(name="lower", args=[parse_expr(MODEL_LABEL_SQL)])
        args += [ast.Call(name="match", args=[lowered_model, ast.Constant(value=pattern)]), ast.Constant(value=family)]
    return ast.Call(name="multiIf", args=[*args, ast.Constant(value=OTHER_FAMILY)])
