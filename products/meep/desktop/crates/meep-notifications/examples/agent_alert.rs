//! Give a workflow a scoped publisher. Swapping in SystemNotifications uses macOS delivery.
use anyhow::Result;
use meep_notifications::{
    Authorization, MemoryNotifications, Namespace, Notification, NotificationCenter, Publisher,
    SystemNotifications,
};

async fn report_done(publisher: &Publisher<'_>) -> Result<()> {
    publisher
        .send(
            "complete",
            &Notification {
                title: "Report ready".into(),
                body: "Your weekly review is ready to open.".into(),
                ..Default::default()
            },
        )
        .await
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    if std::env::args().nth(1).as_deref() == Some("--status") {
        println!("{:?}", SystemNotifications.authorization().await?);
        return Ok(());
    }
    let center = MemoryNotifications::new(Authorization::Authorized);
    let scope = Namespace::new("weekly-review")?;
    let publisher = Publisher::new(&center, scope.clone());
    report_done(&publisher).await?;
    for (_, notice) in center.entries(&scope) {
        println!("{}", notice.title);
    }
    publisher.cancel("complete").await?;
    Ok(())
}
