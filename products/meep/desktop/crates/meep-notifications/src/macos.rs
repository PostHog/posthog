use super::*;
use anyhow::{Context, bail};
use block2::RcBlock;
use objc2::rc::Retained;
use objc2_foundation::{NSArray, NSBundle, NSError, NSString};
use objc2_user_notifications::*;
use std::sync::Mutex;
fn center() -> Result<Retained<UNUserNotificationCenter>> {
    // Apple's API raises an ObjC exception outside an application bundle.
    if NSBundle::mainBundle().bundleIdentifier().is_none() {
        bail!("System notifications require an application bundle");
    }
    Ok(UNUserNotificationCenter::currentNotificationCenter())
}
fn error_text(error: *mut NSError) -> Option<String> {
    // Apple's completion handler guarantees a live NSError for this call.
    unsafe { error.as_ref().map(|e| e.localizedDescription().to_string()) }
}
#[async_trait]
impl NotificationCenter for SystemNotifications {
    async fn request_authorization(&self) -> Result<Authorization> {
        let rx = {
            let center = center()?;
            let (tx, rx) = tokio::sync::oneshot::channel();
            let tx = Mutex::new(Some(tx));
            let callback =
                RcBlock::new(move |granted: objc2::runtime::Bool, error: *mut NSError| {
                    if let Some(tx) = tx.lock().unwrap().take() {
                        let _ = tx.send((granted.as_bool(), error_text(error)));
                    }
                });
            center.requestAuthorizationWithOptions_completionHandler(
                UNAuthorizationOptions::Alert | UNAuthorizationOptions::Sound,
                &callback,
            );
            rx
        };
        let (_, error) = tokio::time::timeout(Duration::from_secs(300), rx)
            .await
            .context("Notification permission request timed out")??;
        if let Some(error) = error {
            bail!("{error}");
        }

        self.authorization().await
    }
    async fn authorization(&self) -> Result<Authorization> {
        let rx = {
            let center = center()?;
            let (tx, rx) = tokio::sync::oneshot::channel();
            let tx = Mutex::new(Some(tx));
            let callback =
                RcBlock::new(move |settings: std::ptr::NonNull<UNNotificationSettings>| {
                    let settings = unsafe { settings.as_ref() };
                    let status = match settings.authorizationStatus() {
                        UNAuthorizationStatus::Authorized => Authorization::Authorized,
                        UNAuthorizationStatus::Denied => Authorization::Denied,
                        UNAuthorizationStatus::Provisional => Authorization::Provisional,
                        _ => Authorization::NotDetermined,
                    };
                    if let Some(tx) = tx.lock().unwrap().take() {
                        let _ = tx.send(status);
                    }
                });
            center.getNotificationSettingsWithCompletionHandler(&callback);
            rx
        };
        Ok(tokio::time::timeout(Duration::from_secs(10), rx)
            .await
            .context("Could not read notification settings")??)
    }
    async fn submit(
        &self,
        key: &str,
        scope: &Namespace,
        notification: &Notification,
    ) -> Result<()> {
        let rx = {
            let center = center()?;
            let content = UNMutableNotificationContent::new();
            content.setTitle(&NSString::from_str(&notification.title));
            content.setBody(&NSString::from_str(&notification.body));
            content.setThreadIdentifier(&NSString::from_str(scope.as_str()));
            if notification.sound {
                content.setSound(Some(&UNNotificationSound::defaultSound()));
            }
            if let Some(category) = &notification.category {
                content.setCategoryIdentifier(&NSString::from_str(category));
            }
            let trigger = notification.delay.map(|delay| {
                UNTimeIntervalNotificationTrigger::triggerWithTimeInterval_repeats(
                    delay.as_secs_f64().max(1.),
                    false,
                )
            });
            let request = UNNotificationRequest::requestWithIdentifier_content_trigger(
                &NSString::from_str(key),
                &content,
                trigger.as_deref().map(|t| &**t),
            );
            let (tx, rx) = tokio::sync::oneshot::channel();
            let tx = Mutex::new(Some(tx));
            let callback = RcBlock::new(move |error: *mut NSError| {
                if let Some(tx) = tx.lock().unwrap().take() {
                    let _ = tx.send(error_text(error));
                }
            });
            center.addNotificationRequest_withCompletionHandler(&request, Some(&callback));
            rx
        };
        if let Some(error) = tokio::time::timeout(Duration::from_secs(10), rx)
            .await
            .context("Notification submission timed out")??
        {
            bail!("{error}");
        }
        Ok(())
    }
    async fn remove(&self, key: &str) -> Result<()> {
        let center = center()?;
        let ids = NSArray::from_retained_slice(&[NSString::from_str(key)]);
        center.removePendingNotificationRequestsWithIdentifiers(&ids);
        center.removeDeliveredNotificationsWithIdentifiers(&ids);
        Ok(())
    }

    async fn clear(&self, scope: &Namespace) -> Result<()> {
        let prefix = scope.prefix();
        let mut ids = {
            let center = center()?;
            let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
            let pending_tx = tx.clone();
            let pending = RcBlock::new(
                move |requests: std::ptr::NonNull<NSArray<UNNotificationRequest>>| {
                    let ids = unsafe { requests.as_ref() }
                        .iter()
                        .map(|r| r.identifier().to_string())
                        .collect::<Vec<_>>();
                    let _ = pending_tx.send(ids);
                },
            );
            let delivered = RcBlock::new(
                move |notifications: std::ptr::NonNull<NSArray<UNNotification>>| {
                    let ids = unsafe { notifications.as_ref() }
                        .iter()
                        .map(|n| n.request().identifier().to_string())
                        .collect::<Vec<_>>();
                    let _ = tx.send(ids);
                },
            );
            center.getPendingNotificationRequestsWithCompletionHandler(&pending);
            center.getDeliveredNotificationsWithCompletionHandler(&delivered);
            rx
        };
        let matching = tokio::time::timeout(Duration::from_secs(2), async {
            let mut matching = Vec::new();
            for _ in 0..2 {
                let batch = ids
                    .recv()
                    .await
                    .context("Notification enumeration interrupted")?;
                matching.extend(batch.into_iter().filter(|id| id.starts_with(&prefix)));
            }
            anyhow::Ok(matching)
        })
        .await??;
        if !matching.is_empty() {
            let identifiers = matching
                .iter()
                .map(|id| NSString::from_str(id))
                .collect::<Vec<_>>();
            let ids = NSArray::from_retained_slice(&identifiers);
            let center = center()?;
            center.removePendingNotificationRequestsWithIdentifiers(&ids);
            center.removeDeliveredNotificationsWithIdentifiers(&ids);
        }
        Ok(())
    }
}
