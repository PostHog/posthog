#![cfg(unix)]
use anyhow::{Result, bail};
use meep_ipc::{
    broker::{RpcConnections, RpcService},
    client::{HOST_TOKEN, request},
    socket::Socket,
};
use meep_protocol::Rpc;
use serde_json::json;
use std::{fs, os::unix::fs::PermissionsExt, sync::Arc, time::Duration};
use tokio::{io::AsyncWriteExt, net::UnixStream};

struct Echo;
#[async_trait::async_trait]
impl RpcService for Echo {
    fn authorize_session(&self, _: &Rpc) -> Result<()> {
        bail!("Unknown session")
    }
    async fn handle(self: Arc<Self>, mut stream: UnixStream, _: &str, rpc: Rpc) -> Result<()> {
        stream
            .write_all(format!("{}\n", json!({"result":rpc.method})).as_bytes())
            .await?;
        Ok(())
    }
}

#[tokio::test]
async fn host_requests_and_session_denials_share_a_private_socket() -> Result<()> {
    let root = tempfile::tempdir_in("/tmp")?;
    let token = Arc::new("a".repeat(64));
    let credential = root.path().join(HOST_TOKEN);
    fs::write(&credential, token.as_bytes())?;
    fs::set_permissions(&credential, fs::Permissions::from_mode(0o600))?;
    let path = root.path().join("broker.sock");
    let socket = Socket::bind(path.clone())?;
    assert_eq!(path.metadata()?.permissions().mode() & 0o777, 0o600);
    let server = async {
        let mut connections = RpcConnections::default();
        for _ in 0..2 {
            let (stream, _) = socket.listener.accept().await?;
            connections.accept(Arc::new(Echo), stream, token.clone());
        }
        while let Some(join) = connections.join_next().await {
            join?;
        }
        anyhow::Ok(())
    };
    let client = async {
        let mut rpc: Rpc = serde_json::from_value(json!({"method":"ping","params":{}}))?;
        assert_eq!(
            request(root.path(), rpc.clone(), Duration::from_secs(4)).await?,
            json!("ping")
        );
        rpc.session_token = Some("unknown".into());
        assert!(
            request(root.path(), rpc, Duration::from_secs(4))
                .await
                .unwrap_err()
                .to_string()
                .contains("Unknown session")
        );
        anyhow::Ok(())
    };
    tokio::try_join!(server, client)?;
    drop(socket);
    assert!(!path.exists());
    Ok(())
}
