"""hogli git:signing-key: create a Secure Enclave key and point git commit signing at it.

macOS 26 ships `ssh-keychain.dylib`, a security key provider for OpenSSH that keeps the
private key inside the Secure Enclave. The key cannot be exported or synced to another device.
The key signs without a Touch ID prompt, also while the screen is locked, so agents can
still sign commits when the engineer is away from the laptop.
"""

from __future__ import annotations

import os
import shlex
import shutil
import platform
import tempfile
import subprocess
from pathlib import Path
from typing import Final

import click

PROVIDER: Final = Path("/usr/lib/ssh-keychain.dylib")
# Homebrew OpenSSH can come first on PATH and may not load Apple's provider.
SSH_KEYGEN: Final = Path("/usr/bin/ssh-keygen")
KEY_LABEL: Final = "git-signing"
SSH_DIR: Final = Path.home() / ".ssh"
KEY_PATH: Final = SSH_DIR / "id_ecdsa_sk_git_signing"
SIGN_PROGRAM_PATH: Final = SSH_DIR / "ssh-keygen-secure-enclave"

# git calls ssh-keygen without a provider flag, and SSH_SK_PROVIDER is missing in IDEs,
# launchd jobs and agent shells. The wrapper sets the provider for every git process.
SIGN_PROGRAM: Final = f"""#!/bin/sh
SSH_SK_PROVIDER={PROVIDER} exec {SSH_KEYGEN} "$@"
"""

GIT_VALUES: Final = {
    "gpg.format": "ssh",
    "user.signingkey": str(KEY_PATH),
    "gpg.ssh.program": str(SIGN_PROGRAM_PATH),
    "commit.gpgsign": "true",
}


def public_key_identity(public_key_line: str) -> str:
    """Return the key type and key blob, without the comment that ssh-keygen -K writes."""
    return " ".join(public_key_line.split()[:2])


def pick_new_key(before: set[str], after: dict[str, Path]) -> Path:
    """Return the key handle that is in `after` but not in `before`.

    The provider exports every Secure Enclave key on the Mac, so other keys can be present.
    """
    new_handles = [handle for identity, handle in after.items() if identity not in before]
    if len(new_handles) != 1:
        raise click.ClickException(
            f"Expected one new Secure Enclave key, found {len(new_handles)}. "
            f"Check `sc_auth list-ctk-identities` for the `{KEY_LABEL}` key."
        )
    return new_handles[0]


def add_allowed_signer(path: Path, email: str, public_key_line: str) -> bool:
    """Append the key to an allowed signers file, unless the file already lists it."""
    identity = public_key_identity(public_key_line)
    existing = path.read_text() if path.exists() else ""
    if identity in existing:
        return False
    separator = "\n" if existing and not existing.endswith("\n") else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{existing}{separator}{email} namespaces="git" {identity}\n')
    return True


def git_config_command(repo: Path | None) -> list[str]:
    """Return the git config command for one target, where `None` is the global config."""
    if repo is None:
        return ["git", "config", "--global"]
    return ["git", "-C", str(repo), "config", "--local"]


def effective_config_command(repo: Path | None) -> list[str]:
    """Return the git config command that reads the merged config a target sees."""
    if repo is None:
        return ["git", "config"]
    return ["git", "-C", str(repo), "config"]


def repo_root(path: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(path.expanduser()), "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise click.ClickException(f"{path} is not a git repository.")
    return Path(result.stdout.strip())


class SecureEnclaveSigningSetup:
    def __init__(self, use_global: bool, repos: tuple[Path, ...]) -> None:
        self.use_global = use_global
        self.repos = repos
        self.targets: list[Path | None] = []
        self.previous_settings: dict[Path | None, dict[str, str | None]] = {}

    def _check_platform(self) -> None:
        if platform.system() != "Darwin" or not PROVIDER.exists() or shutil.which("sc_auth") is None:
            raise click.ClickException(f"This needs macOS 26 or later, which ships {PROVIDER} and sc_auth.")

    def _choose_targets(self) -> list[Path | None]:
        if self.use_global and self.repos:
            raise click.ClickException("Pass either --global or --repo, not both.")
        if self.use_global:
            return [None]
        if self.repos:
            return [repo_root(repo) for repo in self.repos]
        choice = click.prompt(
            "Where should git sign with this key? "
            "repo: this repository and its worktrees. global: every repository. list: repositories you name",
            type=click.Choice(["repo", "global", "list"]),
            default="repo",
        )
        if choice == "global":
            return [None]
        if choice == "repo":
            return [repo_root(Path.cwd())]
        paths = click.prompt("Repository paths, separated by commas")
        return [repo_root(Path(path.strip())) for path in paths.split(",") if path.strip()]

    def _git_config_get(self, command: list[str], setting: str) -> str | None:
        result = subprocess.run([*command, "--get", setting], capture_output=True, text=True)
        return result.stdout.strip() or None

    def _confirm(self) -> None:
        if KEY_PATH.exists():
            click.echo(f"Using the existing Secure Enclave key at {KEY_PATH}.")
        else:
            click.echo(f"This creates a new signing key labeled `{KEY_LABEL}` inside the Mac's Secure Enclave.")
            click.echo("The private key never leaves the Secure Enclave and can't be exported.")
            click.echo("Any process running as you can sign with it, also while the screen is locked.")
            click.echo(f"It writes a key handle to {KEY_PATH}. The handle only works with this Mac's Secure Enclave.")
        click.echo("\nThese stop using your current signing key. Current values in effect:")
        for target in self.targets:
            click.echo(f"  {'Global git config (every repository)' if target is None else target}")
            self.previous_settings[target] = {}
            for setting in GIT_VALUES:
                self.previous_settings[target][setting] = self._git_config_get(git_config_command(target), setting)
                effective = self._git_config_get(effective_config_command(target), setting)
                click.echo(f"    {setting} = {effective or '(unset)'}")
        click.echo("SSH logins and pushes keep using your current SSH agent.")
        if None in self.targets:
            click.echo(
                "Devbox commits sign through your forwarded SSH agent, which can't hold this key. "
                "With the global config they stop signing. Use --repo to keep devbox signing on your agent key."
            )
        click.confirm("Continue?", abort=True)

    def _export_keys(self, directory: Path) -> dict[str, Path]:
        """Write a key handle for each Secure Enclave key into `directory`, keyed by public key identity.

        A key handle only references the key in the Secure Enclave. It is not the private key.
        """
        result = subprocess.run(
            [str(SSH_KEYGEN), "-K", "-N", "", "-w", str(PROVIDER)],
            cwd=directory,
            capture_output=True,
            text=True,
        )
        # Before the first key exists, the provider has nothing to export and ssh-keygen fails.
        if result.returncode != 0:
            return {}
        return {
            public_key_identity(public_path.read_text()): public_path.with_suffix("")
            for public_path in directory.glob("*.pub")
        }

    def _create_key(self) -> None:
        subprocess.run(
            ["sc_auth", "create-ctk-identity", "-l", KEY_LABEL, "-k", "p-256-ne", "-t", "none"],
            check=True,
        )

    def _install_key(self, handle: Path) -> None:
        SSH_DIR.mkdir(mode=0o700, exist_ok=True)
        shutil.copyfile(handle, KEY_PATH)
        KEY_PATH.chmod(0o600)
        shutil.copyfile(handle.with_name(f"{handle.name}.pub"), f"{KEY_PATH}.pub")

    def _create_and_install_key(self) -> None:
        with tempfile.TemporaryDirectory() as before_dir, tempfile.TemporaryDirectory() as after_dir:
            before = set(self._export_keys(Path(before_dir)))
            self._create_key()
            self._install_key(pick_new_key(before, self._export_keys(Path(after_dir))))

    def _install_sign_program(self) -> None:
        SIGN_PROGRAM_PATH.write_text(SIGN_PROGRAM)
        SIGN_PROGRAM_PATH.chmod(0o755)

    def _test_sign(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "payload"
            payload.write_text("hogli git:signing-key test\n")
            result = subprocess.run(
                [str(SIGN_PROGRAM_PATH), "-Y", "sign", "-n", "git", "-f", str(KEY_PATH), str(payload)],
                capture_output=True,
                text=True,
            )
        if result.returncode != 0:
            raise click.ClickException(f"The test signature failed:\n{result.stderr.strip()}")
        click.echo("A test signature with the key worked.")

    def _gh_env(self) -> dict[str, str]:
        # hogli loads .env.local, which can hold an application GITHUB_TOKEN. The key must go
        # to the engineer's own account, so gh uses its stored login instead.
        return {key: value for key, value in os.environ.items() if key not in ("GH_TOKEN", "GITHUB_TOKEN")}

    def _gh(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["gh", *args], capture_output=True, text=True, env=self._gh_env())

    def _is_on_github(self, login: str) -> bool:
        # The list of a user's signing keys is public, so this needs no extra gh scope.
        result = self._gh("api", f"users/{login}/ssh_signing_keys", "--jq", ".[].key")
        public_key = public_key_identity(Path(f"{KEY_PATH}.pub").read_text())
        return public_key in {public_key_identity(line) for line in result.stdout.splitlines()}

    def _add_to_github(self) -> bool:
        title = f"Secure Enclave ({platform.node().split('.')[0]})"
        result = self._gh("ssh-key", "add", f"{KEY_PATH}.pub", "--type", "signing", "--title", title)
        return result.returncode == 0

    def _print_manual_github_steps(self) -> None:
        subprocess.run(["pbcopy"], input=Path(f"{KEY_PATH}.pub").read_text(), text=True)
        subprocess.run(["open", "https://github.com/settings/ssh/new"])
        click.echo("Add the key to GitHub in the browser page that just opened. The public key is on your clipboard.")
        click.echo("Set the key type to Signing Key, paste the key and save.")
        click.echo("Git config stays as it is until GitHub has the key, because pushes of unverified commits fail.")

    def _wait_for_manual_github_step(self, login: str | None) -> None:
        self._print_manual_github_steps()
        while True:
            click.confirm("Did you save the key on GitHub?", default=True, abort=True)
            # Without a gh login there is no way to check, so the answer is trusted.
            if login is None or self._is_on_github(login):
                return
            click.echo(f"GitHub doesn't list this signing key for {login} yet. Check that the key type is Signing Key.")

    def _register_on_github(self) -> None:
        if shutil.which("gh") is None:
            self._wait_for_manual_github_step(None)
            return
        login = self._gh("api", "user", "--jq", ".login").stdout.strip()
        if not login:
            self._wait_for_manual_github_step(None)
            return
        if self._is_on_github(login):
            click.echo(f"GitHub already has this signing key for {login}.")
            return
        if self._add_to_github():
            click.echo(f"Added the signing key to GitHub for {login}.")
            return
        # No `gh auth refresh --scopes admin:ssh_signing_key` here: the scope would stay on the stored
        # gh token, and any process that reads the token could then add signing keys to the account.
        self._wait_for_manual_github_step(login)

    def _restore_commands(self) -> list[list[str]]:
        commands = []
        for target, settings in self.previous_settings.items():
            for setting, value in settings.items():
                if value is None:
                    commands.append([*git_config_command(target), "--unset", setting])
                else:
                    commands.append([*git_config_command(target), setting, value])
        return commands

    def _configure_git(self) -> None:
        try:
            for target in self.targets:
                for setting, value in GIT_VALUES.items():
                    subprocess.run([*git_config_command(target), setting, value], check=True)
        except subprocess.CalledProcessError as error:
            for command in self._restore_commands():
                subprocess.run(command, capture_output=True)
            raise click.ClickException(f"Writing git config failed, so the previous settings were restored: {error}")

    def _update_allowed_signers(self) -> None:
        # Without the key in this file, `git log --show-signature` reports "No principal matched".
        public_key_line = Path(f"{KEY_PATH}.pub").read_text()
        for target in self.targets:
            command = effective_config_command(target)
            signers_file = self._git_config_get([*command, "--type=path"], "gpg.ssh.allowedSignersFile")
            email = self._git_config_get(command, "user.email")
            if signers_file is None or email is None:
                continue
            if add_allowed_signer(Path(signers_file), email, public_key_line):
                click.echo(f"Added the key to your allowed signers file {signers_file}.")

    def _warn_about_overrides(self) -> None:
        if None not in self.targets:
            return
        if subprocess.run(["git", "rev-parse", "--git-dir"], capture_output=True).returncode != 0:
            return
        for setting, value in GIT_VALUES.items():
            result = subprocess.run(
                ["git", "config", "--show-origin", "--get", setting], capture_output=True, text=True
            )
            origin, _, effective = result.stdout.strip().partition("\t")
            if effective != value:
                click.echo(f"Warning: in this repository, {origin} sets {setting} = {effective}, not {value}.")

    def _print_undo_steps(self) -> None:
        click.echo("\nTo go back to your previous signing setup:")
        for command in self._restore_commands():
            click.echo(f"  {shlex.join(command)}")
        click.echo("To delete the Secure Enclave key as well:")
        click.echo(f"  sc_auth list-ctk-identities   # find the hash of the `{KEY_LABEL}` key")
        click.echo(f"  sc_auth delete-ctk-identity -h <hash> && rm {KEY_PATH} {KEY_PATH}.pub")
        click.echo("Keep your previous signing key on GitHub, so commits you already pushed stay verified.")

    def run(self) -> None:
        self._check_platform()
        self.targets = self._choose_targets()
        self._confirm()
        if not KEY_PATH.exists():
            self._create_and_install_key()
        self._install_sign_program()
        # Test first, so a broken key leaves git config untouched.
        self._test_sign()
        # GitHub before git config, so no unverified commits are made if registration stops halfway.
        self._register_on_github()
        self._configure_git()
        self._update_allowed_signers()
        self._warn_about_overrides()
        self._print_undo_steps()


@click.command(name="git:signing-key")
@click.option(
    "--global",
    "use_global",
    is_flag=True,
    help="Write the git settings to your global config, so every repository signs with this key.",
)
@click.option(
    "--repo",
    "repos",
    multiple=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="A repository that signs with this key. Repeat for more. Without --repo or --global, the command asks.",
)
def signing_key(use_global: bool, repos: tuple[Path, ...]) -> None:
    """Set up commit signing with a Secure Enclave key (macOS 26 or later) and register it on GitHub.

    Creates a new SSH key inside the Secure Enclave, so the private key never leaves this Mac.
    It signs without a prompt, also while the screen is locked. No GPG key is involved.
    git uses it instead of your current signing key, for example one in 1Password or Secretive.
    Choose where git signs with it: this repository and its worktrees, a list of repositories,
    or every repository. SSH logins and pushes stay as they are. Devbox commits sign through
    your forwarded SSH agent, so with --global they stop signing. Run it again to reuse the key,
    for example to add another repository. Each Mac needs its own key.

    \b
        hogli git:signing-key
        hogli git:signing-key --repo . --repo ~/code/other-repo
        hogli git:signing-key --global
    """
    SecureEnclaveSigningSetup(use_global, repos).run()
