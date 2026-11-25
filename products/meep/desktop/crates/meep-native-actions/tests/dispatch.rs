use anyhow::Result;
use async_trait::async_trait;
use meep_native_actions::{Action, DesktopActions, dispatch};
use serde_json::Value;
struct NeverCalled;
#[async_trait]
impl DesktopActions for NeverCalled {
    async fn perform(&self, _: &Action) -> Result<Value> {
        panic!("disallowed native effect ran")
    }
}
#[tokio::test]
async fn denied_or_invalid_requests_have_no_effects() {
    let error = dispatch(
        std::sync::Arc::new(NeverCalled),
        &Action::ClipboardRead,
        |_| anyhow::bail!("denied"),
    )
    .await
    .unwrap_err();
    assert_eq!(error.to_string(), "denied");
    for url in [
        "FILE:///var/tmp/example",
        "123:x",
        "not a URL",
        "ssh://host",
    ] {
        assert!(
            dispatch(
                std::sync::Arc::new(NeverCalled),
                &Action::Open { url: url.into() },
                |_| Ok(())
            )
            .await
            .is_err()
        );
    }
}
#[test]
fn callers_text_is_serialized_as_data() {
    let text = "line one\n\"test\"";
    assert_eq!(
        serde_json::to_value(Action::Paste { text: text.into() }).unwrap(),
        serde_json::json!({"operation":"paste","text":text})
    );
}

#[tokio::test]
async fn a_cancelled_paste_finishes_before_the_next_paste_starts() {
    use std::sync::Arc;
    use tokio::sync::{Notify, mpsc};
    struct Clipboard {
        began: mpsc::UnboundedSender<String>,
        finish: Notify,
    }
    #[async_trait]
    impl DesktopActions for Clipboard {
        async fn perform(&self, action: &Action) -> Result<Value> {
            let Action::Paste { text } = action else {
                unreachable!()
            };
            self.began.send(text.clone())?;
            self.finish.notified().await;
            Ok(Value::Null)
        }
    }
    let (began, mut started) = mpsc::unbounded_channel();
    let clipboard = Arc::new(Clipboard {
        began,
        finish: Notify::new(),
    });
    let paste = |text: &str| {
        let backend = clipboard.clone();
        let action = Action::Paste { text: text.into() };
        tokio::spawn(async move { dispatch(backend, &action, |_| Ok(())).await })
    };
    let first = paste("first");
    assert_eq!(started.recv().await.as_deref(), Some("first"));
    first.abort();
    assert!(first.await.unwrap_err().is_cancelled());
    let second = paste("second");
    tokio::task::yield_now().await;
    assert!(started.try_recv().is_err());
    clipboard.finish.notify_one();
    assert_eq!(started.recv().await.as_deref(), Some("second"));
    clipboard.finish.notify_one();
    second.await.unwrap().unwrap();
}
