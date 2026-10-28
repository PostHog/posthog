"""hogli git:signing-key: create a Secure Enclave key and point git commit signing at it.

macOS 26 ships `ssh-keychain.dylib`, a security key provider for OpenSSH that keeps the
private key inside the Secure Enclave. The key cannot be exported or synced to another device.
With `--protection none` it signs without a Touch ID prompt, also while the screen is locked,
so agents can still sign commits when the engineer is away from the laptop.
"""

from __future__ import annotations

import shutil
import platform
import tempfile
import subprocess
from pathlib import Path
from typing import Final

import click

PROVIDER: Final = Path("/usr/lib/ssh-keychain.dylib")
KEY_LABEL: Final = "git-signing"
SSH_DIR: Final = Path.home() / ".ssh"
KEY_PATH: Final = SSH_DIR / "id_ecdsa_sk_git_signing"
SIGN_PROGRAM_PATH: Final = SSH_DIR / "ssh-keygen-secure-enclave"

# git calls ssh-keygen without a provider flag, and SSH_SK_PROVIDER is missing in IDEs,
# launchd jobs and agent shells. The wrapper sets the provider for every git process.
SIGN_PROGRAM: Final = f"""#!/bin/sh
SSH_SK_PROVIDER={PROVIDER} exec /usr/bin/ssh-keygen "$@"
"""

GIT_SETTINGS: Final = ("gpg.format", "user.signingkey", "gpg.ssh.program", "commit.gpgsign")


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


class SecureEnclaveSigningSetup:
    def __init__(self, protection: str, use_global: bool) -> None:
        self.protection = protection
        self.scope = "--global" if use_global else "--local"
        self.previous_settings: dict[str, str | None] = {}

    def _check_platform(self) -> None:
        if platform.system() != "Darwin" or not PROVIDER.exists() or shutil.which("sc_auth") is None:
            raise click.ClickException(f"This needs macOS 26 or later, which ships {PROVIDER} and sc_auth.")
        if (
            self.scope == "--local"
            and subprocess.run(["git", "rev-parse", "--git-dir"], capture_output=True).returncode
        ):
            raise click.ClickException("Run this inside a git repository, or pass --global.")

    def _git_config_get(self, *scope: str, setting: str) -> str | None:
        result = subprocess.run(["git", "config", *scope, "--get", setting], capture_output=True, text=True)
        return result.stdout.strip() or None

    def _confirm(self) -> None:
        if KEY_PATH.exists():
            click.echo(f"Using the existing Secure Enclave key at {KEY_PATH}. --protection has no effect on it.")
        else:
            click.echo(f"This creates a new signing key labeled `{KEY_LABEL}` inside the Mac's Secure Enclave.")
            click.echo("The private key never leaves the Secure Enclave and can't be exported.")
            if self.protection == "none":
                click.echo("Protection: none. Any process running as you can sign, also while the screen is locked.")
            else:
                click.echo("Protection: bio. Each signature needs Touch ID, so signing stops while you are away.")
            click.echo(f"It writes a key handle to {KEY_PATH}. The handle only works with this Mac's Secure Enclave.")
        if self.scope == "--global":
            click.echo("\nEvery repository stops using your current signing key. Your global git config changes.")
        else:
            click.echo("\nThis repository and its worktrees stop using your current signing key.")
            click.echo("Only this repository's git config changes. Pass --global to change every repository.")
        click.echo("Current values in effect here:")
        for setting in GIT_SETTINGS:
            self.previous_settings[setting] = self._git_config_get(self.scope, setting=setting)
            click.echo(f"  {setting} = {self._git_config_get(setting=setting) or '(unset)'}")
        click.echo("SSH logins and pushes keep using your current SSH agent.")
        click.confirm("Continue?", abort=True)

    def _export_keys(self, directory: Path) -> dict[str, Path]:
        """Write a key handle for each Secure Enclave key into `directory`, keyed by public key identity.

        A key handle only references the key in the Secure Enclave. It is not the private key.
        """
        result = subprocess.run(
            ["ssh-keygen", "-K", "-N", "", "-w", str(PROVIDER)],
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
            ["sc_auth", "create-ctk-identity", "-l", KEY_LABEL, "-k", "p-256-ne", "-t", self.protection],
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

    def _configure_git(self) -> None:
        values = {
            "gpg.format": "ssh",
            "user.signingkey": str(KEY_PATH),
            "gpg.ssh.program": str(SIGN_PROGRAM_PATH),
            "commit.gpgsign": "true",
        }
        for setting, value in values.items():
            subprocess.run(["git", "config", self.scope, setting, value], check=True)

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

    def _gh(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["gh", *args], capture_output=True, text=True)

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
        click.echo("Add the key to GitHub by hand. The public key is on your clipboard:")
        click.echo("  1. Open https://github.com/settings/ssh/new")
        click.echo("  2. Set the key type to Signing Key, paste the key and save.")

    def _register_on_github(self) -> None:
        if shutil.which("gh") is None:
            self._print_manual_github_steps()
            return
        login = self._gh("api", "user", "--jq", ".login").stdout.strip()
        if not login:
            self._print_manual_github_steps()
            return
        if self._is_on_github(login):
            click.echo(f"GitHub already has this signing key for {login}.")
            return
        if self._add_to_github():
            click.echo(f"Added the signing key to GitHub for {login}.")
            return
        click.echo("gh needs the admin:ssh_signing_key scope to add a signing key. A browser login opens next.")
        subprocess.run(["gh", "auth", "refresh", "--hostname", "github.com", "--scopes", "admin:ssh_signing_key"])
        if self._add_to_github():
            click.echo(f"Added the signing key to GitHub for {login}.")
            return
        self._print_manual_github_steps()

    def _print_undo_steps(self) -> None:
        click.echo("\nTo go back to your previous signing setup:")
        for setting, value in self.previous_settings.items():
            if value is None:
                click.echo(f"  git config {self.scope} --unset {setting}")
            else:
                click.echo(f'  git config {self.scope} {setting} "{value}"')
        click.echo("To delete the Secure Enclave key as well:")
        click.echo(f"  sc_auth list-ctk-identities   # find the hash of the `{KEY_LABEL}` key")
        click.echo(f"  sc_auth delete-ctk-identity -h <hash> && rm {KEY_PATH} {KEY_PATH}.pub")

    def run(self) -> None:
        self._check_platform()
        self._confirm()
        if not KEY_PATH.exists():
            self._create_and_install_key()
        self._install_sign_program()
        self._configure_git()
        self._test_sign()
        self._register_on_github()
        self._print_undo_steps()


@click.command(name="git:signing-key")
@click.option(
    "--protection",
    type=click.Choice(["bio", "none"]),
    default="bio",
    show_default=True,
    help="bio asks for Touch ID on each signature. none signs without a prompt, also while the screen is locked.",
)
@click.option(
    "--global",
    "use_global",
    is_flag=True,
    help="Write the git settings to your global config, so every repository signs with this key.",
)
def signing_key(protection: str, use_global: bool) -> None:
    """Set up commit signing with a Secure Enclave key (macOS 26 or later) and register it on GitHub.

    Creates a new key inside the Secure Enclave, so the private key never leaves this Mac.
    git uses it instead of your current signing key, for example one in 1Password or Secretive.
    By default only this repository and its worktrees change. SSH logins and pushes stay as
    they are. Run it again to reuse the key and redo the git and GitHub steps.

    \b
        hogli git:signing-key
        hogli git:signing-key --protection none
        hogli git:signing-key --global
    """
    SecureEnclaveSigningSetup(protection, use_global).run()
