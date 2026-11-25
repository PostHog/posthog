//! Exercise the same host dispatch path used by a desktop confirmation button.
use anyhow::Result;
use async_trait::async_trait;
use meep_native_actions::{Action, DesktopActions, dispatch};
use serde_json::{Value, json};

struct Fixture;
#[async_trait]
impl DesktopActions for Fixture {
    async fn perform(&self, _: &Action) -> Result<Value> {
        Ok(json!(true))
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let action = Action::Confirm {
        title: "Archive draft?".into(),
        message: "You can restore it later.".into(),
        confirm_label: Some("Archive".into()),
        cancel_label: None,
    };
    let result = dispatch(std::sync::Arc::new(Fixture), &action, |action| {
        anyhow::ensure!(
            matches!(action, Action::Confirm { .. }),
            "This fixture only allows confirmation"
        );
        Ok(())
    })
    .await?;
    println!("Confirmed: {result}");
    Ok(())
}
