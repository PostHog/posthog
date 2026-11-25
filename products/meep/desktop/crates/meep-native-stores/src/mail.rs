//! Read-only Mail adapters. Run blocking reads off the UI thread, after checking Automation
//! consent and the caller's grant. Dates, page limits and fields sent to callers are host policy.
#[cfg(target_os = "macos")]
use anyhow::Context;
use anyhow::Result;
use serde::Deserialize;
use std::time::Duration;

/// macOS's Automation decision for the host controlling Mail.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Automation {
    Granted,
    NotDetermined,
    Denied,
    /// Mail isn't open, so macOS can't say.
    NotRunning,
}
impl Automation {
    pub fn name(self) -> &'static str {
        match self {
            Self::Granted => "granted",
            Self::NotDetermined => "notDetermined",
            Self::Denied => "denied",
            Self::NotRunning => "mailNotRunning",
        }
    }
}

/// Why Mail didn't answer, in the person's words.
#[derive(Debug, PartialEq)]
pub enum Failure {
    NotRunning,
    Denied,
    /// Asked, and macOS came back without a decision.
    Undecided,
    TimedOut(Duration),
    /// The message or mailbox no longer exists.
    Missing,
    Other(String),
}
impl std::fmt::Display for Failure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotRunning => write!(f, "Mail isn't open. Open the Mail app and try again."),
            Self::Denied => write!(
                f,
                "Allow this app to read Mail in System Settings → Privacy & Security → Automation."
            ),
            Self::Undecided => write!(f, "macOS didn't finish asking to read Mail. Try again."),
            Self::TimedOut(after) => write!(
                f,
                "Mail didn't answer within {} seconds. It may still be loading a large mailbox; try again with a smaller limit.",
                after.as_secs()
            ),
            Self::Missing => write!(f, "That message or mailbox is no longer in Mail."),
            Self::Other(message) => write!(f, "Mail couldn't answer: {message}"),
        }
    }
}
impl std::error::Error for Failure {}

/// An Apple event error from the adapter, as a `Failure`.
pub fn failure(number: i64, message: &str) -> Failure {
    match number {
        // procNotFound, connectionInvalid: not running, or quit mid-call.
        -600 | -609 => Failure::NotRunning,
        // errAEEventNotPermitted, errAEEventWouldRequireUserConsent.
        -1743 | -1744 => Failure::Denied,
        // errAETimeout.
        -1712 => Failure::TimedOut(Duration::ZERO),
        // errAENoSuchObject.
        -1728 => Failure::Missing,
        _ => {
            let message = message.trim().trim_start_matches("Error: ");
            let cut = message.floor_char_boundary(200);
            Failure::Other(if message.is_empty() {
                "unknown error".into()
            } else {
                message[..cut].into()
            })
        }
    }
}

/// A mailbox of one account, by its place in the account's mailbox list: the
/// names from the account down to it (as far as Mail names its containers),
/// and which of the mailboxes with that path it is. Its own name alone doesn't
/// find every mailbox again (Gmail's "Sent Mail" doesn't).
#[derive(Clone, Debug, PartialEq, Deserialize, serde::Serialize)]
pub struct Place {
    /// Mail's account identifier.
    pub account: String,
    pub path: Vec<String>,
    /// 0 unless mailboxes share the path.
    #[serde(default)]
    pub nth: usize,
}
#[derive(Clone, Debug, Deserialize)]
pub struct Mailboxes {
    /// Unread messages in the unified inbox.
    pub unread: u64,
    pub accounts: Vec<Account>,
}
#[derive(Clone, Debug, Deserialize)]
pub struct Account {
    pub id: String,
    pub name: String,
    pub mailboxes: Vec<Folder>,
}
#[derive(Clone, Debug, Deserialize)]
pub struct Folder {
    pub name: String,
    /// From the account down, `name` last.
    #[serde(default)]
    pub path: Vec<String>,
    /// As in `Place`.
    #[serde(default)]
    pub nth: usize,
    #[serde(default)]
    pub unread: u64,
}
/// One page: `count` messages from the newest end of `mailbox` (the unified
/// inbox when `None`), older than `before` or after the message `after`,
/// looking at no more than `scan`.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
pub struct Page {
    pub mailbox: Option<Place>,
    pub count: usize,
    pub scan: usize,
    pub before: Option<String>,
    /// The last message of the previous page: the page continues after it,
    /// including messages from the same second that it didn't show.
    pub after: Option<MessageRef>,
    #[serde(rename = "unreadOnly")]
    pub unread_only: bool,
}
#[derive(Clone, Debug, Default, Deserialize)]
pub struct Person {
    pub name: Option<String>,
    pub address: Option<String>,
}
/// One message, untrimmed: the host chooses the fields and lengths it returns.
#[derive(Clone, Debug, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Summary {
    /// Mail's own ID for the message, unique within the mailbox.
    pub library_id: i64,
    pub account_id: String,
    pub account: Option<String>,
    pub mailbox: String,
    /// From the account down, `mailbox` last.
    #[serde(default)]
    pub mailbox_path: Vec<String>,
    #[serde(default)]
    pub mailbox_nth: usize,
    pub subject: Option<String>,
    /// "Name <address>", as Mail gives it.
    pub sender: Option<String>,
    #[serde(default)]
    pub to: Vec<Person>,
    pub date: Option<chrono::DateTime<chrono::Utc>>,
    #[serde(default)]
    pub read: bool,
    #[serde(default)]
    pub flagged: bool,
    /// The Message-ID header, without angle brackets.
    pub message_id: Option<String>,
    /// Mail couldn't give its headers in time: `to` and `message_id` are
    /// missing, not empty.
    #[serde(default)]
    pub incomplete: bool,
}
#[derive(Clone, Debug, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Message {
    #[serde(flatten)]
    pub summary: Summary,
    #[serde(default)]
    pub cc: Vec<Person>,
    pub text: Option<String>,
    #[serde(default)]
    pub text_clipped: bool,
    #[serde(default)]
    pub attachments: Vec<Attachment>,
}
#[derive(Clone, Debug, Default, Deserialize)]
pub struct Attachment {
    pub name: Option<String>,
    pub size: Option<f64>,
}
/// A message by its mailbox and Mail's ID for it.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MessageRef {
    pub account: String,
    /// The mailbox, as in `Place`.
    pub path: Vec<String>,
    pub nth: usize,
    pub library_id: i64,
}

fn validate_place(account: &str, path: &[String]) -> Result<()> {
    let valid = |s: &str| !s.is_empty() && !s.chars().any(char::is_control);
    anyhow::ensure!(
        valid(account) && !path.is_empty() && path.iter().all(|part| valid(part)),
        "Invalid mailbox location"
    );
    Ok(())
}

impl MessageRef {
    pub fn validate(&self) -> Result<()> {
        anyhow::ensure!(self.library_id > 0, "Invalid message identifier");
        validate_place(&self.account, &self.path)
    }
}

impl Page {
    pub fn validate(&self) -> Result<()> {
        anyhow::ensure!(
            self.count > 0 && self.scan >= self.count,
            "Expected a positive count and a scan at least as large"
        );
        if let Some(place) = &self.mailbox {
            validate_place(&place.account, &place.path)?;
        }
        if let Some(after) = &self.after {
            after.validate()?;
        }
        if let Some(before) = &self.before {
            anyhow::ensure!(self.after.is_none(), "Use one pagination cursor per page");
            before.parse::<chrono::DateTime<chrono::Utc>>()?;
        }
        Ok(())
    }
}

/// Call these blocking operations on a worker thread.
/// Each stops after `deadline` with `Failure::TimedOut`.
pub trait Mail: Send + Sync {
    /// macOS's decision. `ask` shows the system prompt when it was never made;
    /// never pass it from a test.
    fn automation(&self, ask: bool) -> Result<Automation>;
    fn mailboxes(&self, deadline: Duration) -> Result<Mailboxes>;
    fn messages(&self, page: &Page, deadline: Duration) -> Result<Vec<Summary>>;
    /// `Failure::Missing` when it is gone.
    fn message(&self, message: &MessageRef, deadline: Duration) -> Result<Message>;
}

/// The JXA adapter's operations: reads, and nothing else.
pub const OPERATIONS: &[&str] = &["mailboxes", "message"];
/// `mailboxes` and `message`, in JavaScript for Automation.
pub const ADAPTER: &str = include_str!("adapters/mail.js");
/// `messages`, in AppleScript: it reads a page with one Apple event per
/// property for a whole range of messages, which JXA can't send.
pub const PAGE_ADAPTER: &str = include_str!("adapters/mail-page.applescript");
pub struct MailApp;

#[cfg(target_os = "macos")]
mod macos;

#[cfg(not(target_os = "macos"))]
impl Mail for MailApp {
    fn automation(&self, _: bool) -> Result<Automation> {
        anyhow::bail!("{}", crate::UNAVAILABLE);
    }
    fn mailboxes(&self, _: Duration) -> Result<Mailboxes> {
        anyhow::bail!("{}", crate::UNAVAILABLE);
    }
    fn messages(&self, _: &Page, _: Duration) -> Result<Vec<Summary>> {
        anyhow::bail!("{}", crate::UNAVAILABLE);
    }
    fn message(&self, _: &MessageRef, _: Duration) -> Result<Message> {
        anyhow::bail!("{}", crate::UNAVAILABLE);
    }
}
