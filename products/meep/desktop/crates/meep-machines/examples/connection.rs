//! With no arguments this runs a fixture. With a target it opens an idle SSH connection.
use anyhow::{Context, Result};
use async_trait::async_trait;
use meep_machines::{Connection, Connector, RetryPolicy, Session, Status};

struct Fixture;
#[async_trait]
impl Connector for Fixture {
    async fn connect(&self) -> Result<Box<dyn Session>> {
        Ok(Box::new(Fixture))
    }
}
#[async_trait]
impl Session for Fixture {
    async fn closed(&mut self) -> Result<()> {
        std::future::pending().await
    }
    async fn disconnect(self: Box<Self>) -> Result<()> {
        Ok(())
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let Some(target) = args.next() else {
        let connection = Connection::start(Fixture, RetryPolicy::default());
        connection
            .subscribe()
            .wait_for(|s| *s == Status::Connected)
            .await?;
        println!("Connected");
        connection.shutdown().await?;
        println!("Stopped");
        return Ok(());
    };
    #[cfg(unix)]
    {
        use tokio::io::AsyncBufReadExt;
        let mut ssh = meep_machines::ssh::OpenSsh::new(target)?;
        if let Some(config) = args.next() {
            ssh = ssh.with_config(config);
        }
        anyhow::ensure!(
            args.next().is_none(),
            "Usage: connection [TARGET [SSH_CONFIG]]"
        );
        let connection = Connection::start(ssh, RetryPolicy::default());
        let mut status = connection.subscribe();
        let mut lines = tokio::io::BufReader::new(tokio::io::stdin()).lines();
        println!("{:?}", *status.borrow_and_update());
        loop {
            tokio::select! {
                changed = status.changed() => {
                    changed.context("Connection supervisor stopped")?;
                    println!("{:?}", *status.borrow_and_update());
                }
                line = lines.next_line() => match line?.as_deref() {
                    Some("reconnect") => connection.reconnect(),
                    Some("quit") | None => break,
                    _ => println!("Enter reconnect or quit"),
                }
            }
        }
        connection.shutdown().await?;
        println!("{:?}", *status.borrow());
        Ok(())
    }
    #[cfg(not(unix))]
    anyhow::bail!("OpenSSH requires Unix (target {target})")
}
