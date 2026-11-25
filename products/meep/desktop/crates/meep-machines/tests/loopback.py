# /// script
# requires-python = ">=3.11"
# dependencies = ["asyncssh==2.24.1"]
# ///
"""Exercise the connection example against an authenticated, connection-only loopback peer."""
import sys
import asyncio
import tempfile
from pathlib import Path

import asyncssh


async def verify(binary, root):
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    identity = root / "client"
    client_key.write_private_key(identity)
    identity.chmod(0o600)
    authenticated = asyncio.Queue()
    channels = []

    class Peer(asyncssh.SSHServer):
        def connection_made(self, connection):
            self.connection = connection

        def public_key_auth_supported(self):
            return True

        def validate_public_key(self, username, key):
            return username == "fixture" and key == client_key.convert_to_public()

        def auth_completed(self):
            authenticated.put_nowait(self.connection)

        def session_requested(self):
            channels.append("session")
            return False

        def connection_requested(self, *args):
            channels.append("forward")
            return False

        def server_requested(self, *args):
            channels.append("listener")
            return False

    async with await asyncssh.listen("127.0.0.1", 0, server_factory=Peer,
                                     server_host_keys=[host_key], config=None) as server:
        port = server.get_port()
        known = root / "known_hosts"
        known.touch(mode=0o600)
        config = root / "ssh_config"
        config.write_text(f"""Host fixture
    HostName 127.0.0.1
    Port {port}
    User fixture
    IdentityAgent none
    IdentitiesOnly yes
    IdentityFile "{identity}"
    UserKnownHostsFile "{known}"
    GlobalKnownHostsFile /dev/null
""")
        process = await asyncio.create_subprocess_exec(
            binary, "fixture", config, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE)
        try:
            async def state(prefix):
                while line := await process.stdout.readline():
                    line = line.decode().strip()
                    if line.startswith(prefix):
                        return line
                    if line.startswith("Retrying") or line == "Stopped":
                        raise AssertionError(f"Expected {prefix}, got {line}")
                raise AssertionError(f"Client exited before {prefix}")

            failure = await state("Retrying")
            assert "Host key verification failed" in failure, failure
            assert authenticated.empty()
            # The fixture host explicitly trusts its own key before retrying.
            known.write_bytes(f"[127.0.0.1]:{port} ".encode() + host_key.export_public_key())
            process.stdin.write(b"reconnect\n")
            await state("Connected")
            first = await authenticated.get()
            first.abort()
            await state("Retrying")
            await state("Connected")
            second = await authenticated.get()
            process.stdin.write(b"reconnect\n")
            await state("Connected")
            third = await authenticated.get()
            await second.wait_closed()
            process.stdin.write(b"quit\n")
            await process.stdin.drain()
            process.stdin.close()
            await state("Stopped")
            assert await process.wait() == 0
            await third.wait_closed()
            assert not channels, channels
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()


async def main():
    with tempfile.TemporaryDirectory() as folder:
        await asyncio.wait_for(verify(sys.argv[1], Path(folder)), timeout=35)
    sys.stdout.write("Passed host-key refusal, authentication, reconnect after network loss, manual reconnect and shutdown. No remote sessions or forwards opened.\n")


if __name__ == "__main__":
    asyncio.run(main())
