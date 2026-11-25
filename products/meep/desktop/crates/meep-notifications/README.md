# meep-notifications

Copy this directory into a Rust application to send, schedule, replace and cancel OS notifications. The host selects the namespace for each agent, view or workflow. IDs are stable within that namespace. Clearing a publisher removes its pending and delivered cards. Notification Center owns display, Focus and sound.

```rust
use meep_notifications::{Namespace, Notification, Publisher, SystemNotifications};

async fn report_ready() -> anyhow::Result<()> {
    let center = SystemNotifications;
    let publisher = Publisher::new(&center, Namespace::new("reports-agent")?);
    publisher.send("weekly", &Notification {
        title: "Weekly report ready".into(),
        ..Default::default()
    }).await?;
    Ok(())
}
```

In the app settings, read `center.authorization()`. Call `center.request_authorization()` from the user's enable action. Bind the publisher after checking the caller's current grant. Sending checks OS authorization without opening a prompt. The signed macOS application bundle supplies the notification identity. The host owns any notification categories, response delegate, click routing and durable in-app history. `Notification::category` refers to a registered host category.

Use `MemoryNotifications` for previews or implement `NotificationCenter` for another platform. Run `cargo run --example agent_alert` to deliver and cancel a fixture notification. The same example accepts `--status` when built into a Mac application bundle for a read-only check of its real Notification Center authorization.
