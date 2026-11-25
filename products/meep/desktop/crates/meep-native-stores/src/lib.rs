//! Independently selectable platform readers. The host owns caller grants and storage.
#[cfg(feature = "calendar")]
pub mod calendar;
#[cfg(feature = "contacts")]
pub mod contacts;
#[cfg(feature = "mail")]
pub mod mail;
#[cfg(all(target_os = "macos", any(feature = "calendar", feature = "contacts")))]
use anyhow::Context;
use anyhow::Result;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Access {
    NotDetermined,
    Full,
    WriteOnly,
    /// Some of the data (contacts the person picked), where macOS offers it.
    Limited,
    Denied,
    Restricted,
}
impl Access {
    pub fn name(self) -> &'static str {
        match self {
            Self::NotDetermined => "notDetermined",
            Self::Full => "fullAccess",
            Self::WriteOnly => "writeOnly",
            Self::Limited => "limited",
            Self::Denied => "denied",
            Self::Restricted => "restricted",
        }
    }
}
pub trait Privacy: Send + Sync {
    fn access(&self) -> Result<Access>;
    /// Shows the system prompt when access was never decided. Never call it from a test.
    fn request(&self) -> Result<bool>;
}

#[cfg(all(
    not(target_os = "macos"),
    any(feature = "calendar", feature = "contacts", feature = "mail")
))]
const UNAVAILABLE: &str = "This system store requires macOS.";

/// Check the embedding bundle before invoking an API that can terminate a process
/// with a missing privacy usage description.
#[cfg(all(
    target_os = "macos",
    any(feature = "calendar", feature = "contacts", feature = "mail")
))]
fn bundled(what: &str) -> Result<()> {
    use objc2_foundation::{NSBundle, NSString};
    let bundle = NSBundle::mainBundle();
    anyhow::ensure!(
        bundle.bundleIdentifier().is_some(),
        "{what} access requires an application bundle"
    );
    let key = match what {
        "Contacts" => "NSContactsUsageDescription",
        "Mail" => "NSAppleEventsUsageDescription",
        #[cfg(feature = "calendar")]
        "Calendar" if calendar::full_access_api() => "NSCalendarsFullAccessUsageDescription",
        #[cfg(feature = "calendar")]
        "Reminders" if calendar::full_access_api() => "NSRemindersFullAccessUsageDescription",
        "Calendar" => "NSCalendarsUsageDescription",
        "Reminders" => "NSRemindersUsageDescription",
        _ => anyhow::bail!("Unknown system store {what}"),
    };
    let purpose = bundle.objectForInfoDictionaryKey(&NSString::from_str(key));
    anyhow::ensure!(
        purpose
            .as_ref()
            .and_then(|p| p.downcast_ref::<NSString>())
            .is_some_and(|s| !s.to_string().trim().is_empty()),
        "The application's Info.plist must describe {what} access in {key}"
    );
    Ok(())
}
#[cfg(all(target_os = "macos", any(feature = "calendar", feature = "contacts")))]
fn require_read(store: &dyn Privacy, what: &str) -> Result<()> {
    anyhow::ensure!(
        matches!(store.access()?, Access::Full | Access::Limited),
        "{what} read access has not been granted"
    );
    Ok(())
}

/// Waits for the person's answer to a system prompt that `start` shows, handing
/// it the completion block. The framework copies the block.
///
#[cfg(all(target_os = "macos", any(feature = "calendar", feature = "contacts")))]
pub(crate) fn decision(
    what: &str,
    start: impl FnOnce(&block2::DynBlock<dyn Fn(objc2::runtime::Bool, *mut objc2_foundation::NSError)>),
) -> Result<bool> {
    use objc2::runtime::Bool;
    use objc2_foundation::NSError;
    let (tx, rx) = std::sync::mpsc::channel();
    let tx = std::sync::Mutex::new(Some(tx));
    let callback: block2::RcBlock<dyn Fn(Bool, *mut NSError)> =
        block2::RcBlock::new(move |granted: Bool, error: *mut NSError| {
            // The framework keeps this error alive for the duration of the callback.
            let decision = match unsafe { error.as_ref() } {
                Some(error) => Err(anyhow::anyhow!("{}", error.localizedDescription())),
                None => Ok(granted.as_bool()),
            };
            if let Some(tx) = tx.lock().unwrap().take() {
                let _ = tx.send(decision);
            }
        });
    start(&callback);
    rx.recv_timeout(std::time::Duration::from_secs(300))
        .with_context(|| format!("{what} permission request timed out"))?
}
/// Text that says something, or nothing.
#[cfg(all(target_os = "macos", any(feature = "calendar", feature = "contacts")))]
pub(crate) fn text(s: Option<objc2::rc::Retained<objc2_foundation::NSString>>) -> Option<String> {
    s.map(|s| s.to_string()).filter(|s| !s.trim().is_empty())
}
