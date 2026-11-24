"""Every decision the proof makes, as pure functions over plain values.

The shell around it reads git, the GitHub API and the registry, runs pnpm, and passes what it
read in here. The shell may interleave reads and checks, but it never decides: every refusal is
raised in this package. tests/test_package.py keeps the side-effecting modules out of it.
"""
