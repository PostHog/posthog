# meep-machines

Keep an authenticated connection to a server on behalf of a desktop application. Copy this directory and add it as a path dependency. The connection handle owns one supervisor. The host owns its machine list, endpoint configuration and any future assignment to an agent.

```rust
use meep_machines::{Connection, RetryPolicy, Status, ssh::OpenSsh};

async fn connect() -> anyhow::Result<()> {
    let connection = Connection::start(OpenSsh::new("build-server")?, RetryPolicy::default());
    let mut status = connection.subscribe();
    status.wait_for(|s| matches!(s, Status::Connected)).await?;
    // Keep the handle in application state for as long as this machine should stay online.
    connection.shutdown().await?;
    Ok(())
}
```

The Unix adapter starts the system OpenSSH client with a private control socket, batch authentication, strict host-key verification and protocol keepalives. The authenticated master acknowledges a local control check before the supervisor publishes `Connected`. It requests zero remote sessions. A server can disallow shell access and still work. The embedding host supplies a trusted SSH alias or destination and can pass its own SSH config with `with_config`. Set up trusted host keys and authentication in advance.

Watch `Connecting`, `Connected`, `Retrying { error, delay }` and `Stopped` for feedback. A watch receiver reports the latest state and may skip intermediate states. The default retry schedule starts at one second and caps at two minutes. A minute of stable uptime resets it. Supply a custom `RetryPolicy` or call `reconnect()` on a network change. Dropping the handle signals shutdown. Await `shutdown()` when cleanup must finish before proceeding. A different transport can implement `Connector` and `Session`.

```sh
cargo run --example connection
cargo run --example connection -- build-server
cargo run --example connection -- my-alias /path/to/ssh_config
```

With a destination, the example watches the connection until EOF or `quit`. Type `reconnect` to replace the active connection. With no arguments it uses an in-memory peer. To run the authenticated loopback test from this directory, set the binary path to Cargo's example output for your checkout.

```sh
cargo build --example connection
uv run --script tests/loopback.py /path/to/target/debug/examples/connection
```

The fixture generates temporary keys, rejects the first untrusted connection and interrupts an authenticated peer. It checks automatic recovery, manual reconnect, shutdown and the absence of remote channels.
