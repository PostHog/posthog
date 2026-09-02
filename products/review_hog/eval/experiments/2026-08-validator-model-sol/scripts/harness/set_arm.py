import re
import sys
import pathlib

arm = sys.argv[1]
p = pathlib.Path(__file__).resolve().parents[7] / "products/review_hog/backend/reviewer/constants.py"
s = p.read_text()
L = """VALIDATION_RUNTIME_ADAPTER: RuntimeAdapter | None = RuntimeAdapter.CLAUDE
VALIDATION_MODEL: str | None = "claude-opus-5"
VALIDATION_REASONING_EFFORT: ReasoningEffort | None = ReasoningEffort.XHIGH
VALIDATION_INITIAL_PERMISSION_MODE: str | None = None
"""
M = """VALIDATION_RUNTIME_ADAPTER: RuntimeAdapter | None = RuntimeAdapter.CODEX  # EXPERIMENT ARM (revert)
VALIDATION_MODEL: str | None = "gpt-5.6-sol"  # EXPERIMENT ARM (revert)
VALIDATION_REASONING_EFFORT: ReasoningEffort | None = ReasoningEffort.XHIGH
VALIDATION_INITIAL_PERMISSION_MODE: str | None = "full-access"  # EXPERIMENT ARM (revert)
"""
N = """VALIDATION_RUNTIME_ADAPTER: RuntimeAdapter | None = RuntimeAdapter.CLAUDE
VALIDATION_MODEL: str | None = "claude-sonnet-5"  # EXPERIMENT ARM (revert)
VALIDATION_REASONING_EFFORT: ReasoningEffort | None = ReasoningEffort.XHIGH
VALIDATION_INITIAL_PERMISSION_MODE: str | None = None
"""
pat = re.compile(
    r"VALIDATION_RUNTIME_ADAPTER: .*?\nVALIDATION_MODEL: .*?\nVALIDATION_REASONING_EFFORT: .*?\nVALIDATION_INITIAL_PERMISSION_MODE: .*?\n",
    re.S,
)
assert len(pat.findall(s)) == 1
s2 = pat.sub({"L": L, "M": M, "N": N}[arm], s)
p.write_text(s2)
print("arm", arm, "written; block now:")
block = pat.search(s2)
assert block is not None
print(block.group(0))
