"""The pnpm commands a proof replays."""


def replay_commands(updates: list[str], install: bool, recursive: bool) -> list[list[str]]:
    """The pnpm commands Renovate runs for one lockfile.

    Renovate runs `pnpm install` when it edits a manifest. It then runs one `pnpm update` for the
    dependencies it moves inside a range that it leaves unchanged.
    """
    flags = ["--lockfile-only", *(["--recursive"] if recursive else []), "--ignore-scripts", "--ignore-pnpmfile"]
    commands = []
    if install:
        # A runner sets `CI`, and `pnpm install` then refuses to change the lockfile without this flag.
        commands.append(["pnpm", "install", *flags, "--no-frozen-lockfile"])
    if updates:
        commands.append(["pnpm", "update", "--no-save", *updates, *flags])
    return commands
