//! A private, one-request workspace service using the ordinary authenticated client.
#[cfg(unix)]
mod local {
    use anyhow::{Result, bail, ensure};
    use meep_ipc::{
        broker::{RpcConnections, RpcService},
        client,
        socket::Socket,
    };
    use meep_protocol::Rpc;
    use serde_json::{Value, json};
    use std::{
        fs::{File, OpenOptions},
        io::{Read, Write},
        os::unix::fs::OpenOptionsExt,
        sync::Arc,
        time::Duration,
    };
    use tokio::{io::AsyncWriteExt, net::UnixStream};

    struct Service;
    #[async_trait::async_trait]
    impl RpcService for Service {
        fn authorize_session(&self, _: &Rpc) -> Result<()> {
            bail!("This example accepts only its workspace client")
        }
        async fn handle(self: Arc<Self>, mut stream: UnixStream, _: &str, rpc: Rpc) -> Result<()> {
            let result = if rpc.method == "workspace.name" {
                json!({"result":"Studio"})
            } else {
                json!({"error":"Unknown method"})
            };
            let mut bytes = serde_json::to_vec(&result)?;
            bytes.push(b'\n');
            stream.write_all(&bytes).await?;
            Ok(())
        }
    }
    pub async fn run() -> Result<()> {
        let dir = tempfile::Builder::new()
            .prefix("meep-")
            .tempdir_in("/tmp")?;
        let mut random = [0u8; 32];
        File::open("/dev/urandom")?.read_exact(&mut random)?;
        let token: String = random.iter().map(|b| format!("{b:02x}")).collect();
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(dir.path().join(client::HOST_TOKEN))?
            .write_all(token.as_bytes())?;
        let socket = Socket::bind(dir.path().join("broker.sock"))?;
        let serve = async {
            let (stream, _) = socket.listener.accept().await?;
            let mut connections = RpcConnections::default();
            connections.accept(Arc::new(Service), stream, Arc::new(token));
            connections.join_next().await.expect("accepted request")?;
            Ok(())
        };
        let request = Rpc {
            method: "workspace.name".into(),
            params: json!({}),
            view_id: None,
            session_token: None,
            view_revision: None,
        };
        let ((), name): ((), Value) = tokio::try_join!(
            serve,
            client::request(dir.path(), request, Duration::from_secs(3))
        )?;
        ensure!(name == "Studio");
        println!("The workspace service replied with {name}.");
        Ok(())
    }
}
#[cfg(unix)]
#[tokio::main(flavor = "current_thread")]
async fn main() -> anyhow::Result<()> {
    local::run().await
}
#[cfg(not(unix))]
fn main() {
    println!("The workspace round trip uses Unix sockets.");
}
