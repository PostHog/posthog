use meep_notifications::MemoryNotifications as Inbox;
use meep_notifications::{Authorization, Namespace, Notification, Publisher};

#[tokio::test]
async fn one_caller_cannot_replace_or_clear_anothers_delivery() {
    let inbox = Inbox::new(Authorization::Provisional);
    let a = Publisher::new(&inbox, Namespace::new("agent").unwrap());
    let b = Publisher::new(&inbox, Namespace::new("agent:1").unwrap());
    let mut notice = Notification {
        title: "Started".into(),
        ..Default::default()
    };
    a.send("1:done", &notice).await.unwrap();
    b.send("done", &notice).await.unwrap();
    notice.title = "Completed".into();
    b.send("done", &notice).await.unwrap();
    a.clear().await.unwrap();
    let other = Namespace::new("agent:1").unwrap();
    assert!(inbox.entries(&Namespace::new("agent").unwrap()).is_empty());
    assert_eq!(inbox.entries(&other), [("done".into(), notice)]);
    a.cancel("1:done").await.unwrap();
    assert_eq!(inbox.entries(&other).len(), 1);
    b.cancel("done").await.unwrap();
    assert!(inbox.entries(&other).is_empty());
}

#[tokio::test]
async fn sending_never_requests_consent() {
    let inbox = Inbox::new(Authorization::NotDetermined);
    let publisher = Publisher::new(&inbox, Namespace::new("task").unwrap());
    let notice = Notification {
        title: "Ready".into(),
        ..Default::default()
    };
    assert_eq!(
        publisher
            .send("one", &notice)
            .await
            .unwrap_err()
            .to_string(),
        "System notifications are not authorized"
    );
    assert!(inbox.entries(&Namespace::new("task").unwrap()).is_empty());
}
