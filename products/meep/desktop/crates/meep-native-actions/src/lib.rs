//! Typed desktop effects. The embedding host approves each action at the point of use.
use anyhow::{Result, ensure};
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde::Serialize;
use serde_json::Value;

#[derive(Clone, Debug, Serialize)]
#[serde(
    tag = "operation",
    rename_all = "camelCase",
    rename_all_fields = "camelCase"
)]
pub enum Action {
    Confirm {
        title: String,
        message: String,
        confirm_label: Option<String>,
        cancel_label: Option<String>,
    },
    Pick {
        title: String,
        multiple: bool,
        extensions: Vec<String>,
    },
    PickFolder {
        title: String,
    },
    Save {
        title: String,
        name: String,
    },
    ClipboardRead,
    Paste {
        text: String,
    },
    SelectedText,
    Open {
        url: String,
    },
    CalendarCreate {
        title: String,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
        calendar: Option<String>,
        notes: Option<String>,
        location: Option<String>,
    },
    ReminderCreate {
        title: String,
        list: Option<String>,
        due: Option<DateTime<Utc>>,
        notes: Option<String>,
    },
}

impl Action {
    /// Operation name in the rendered view SDK. File picker results belong to the host.
    pub fn method(&self) -> &'static str {
        match self {
            Self::Confirm { .. } => "native.confirm",
            Self::Pick { .. } => "native.files.pick",
            Self::PickFolder { .. } => "native.files.pickFolder",
            Self::Save { .. } => "native.files.saveText",
            Self::ClipboardRead => "native.clipboard.readText",
            Self::Paste { .. } => "native.clipboard.paste",
            Self::SelectedText => "native.selection.readText",
            Self::Open { .. } => "native.apps.open",
            Self::CalendarCreate { .. } => "native.calendar.create",
            Self::ReminderCreate { .. } => "native.systemReminders.create",
        }
    }

    fn validate(&self) -> Result<()> {
        match self {
            Self::CalendarCreate {
                title, start, end, ..
            } => {
                ensure!(!title.trim().is_empty(), "Enter an event title");
                ensure!(start < end, "The event must end after it starts");
            }
            Self::ReminderCreate { title, .. } => {
                ensure!(!title.trim().is_empty(), "Enter a reminder title")
            }
            Self::Open { url } => {
                let (scheme, _) = url
                    .split_once(':')
                    .ok_or_else(|| anyhow::anyhow!("Expected an app URL"))?;
                ensure!(
                    scheme.starts_with(|c: char| c.is_ascii_alphabetic())
                        && scheme
                            .bytes()
                            .all(|c| c.is_ascii_alphanumeric() || b"+-.".contains(&c))
                        && !url.chars().any(char::is_control)
                        && !BLOCKED_SCHEMES.contains(&scheme.to_ascii_lowercase().as_str()),
                    "Unsupported app URL"
                );
            }
            _ => {}
        }
        Ok(())
    }
}

#[async_trait]
pub trait DesktopActions: Send + Sync {
    async fn perform(&self, action: &Action) -> Result<Value>;
}

/// Run the host's grant and foreground-gesture check immediately before invoking the adapter.
/// The pasteboard is shared by all callers in this process.
pub async fn dispatch(
    backend: std::sync::Arc<dyn DesktopActions>,
    action: &Action,
    authorize: impl FnOnce(&Action) -> Result<()>,
) -> Result<Value> {
    static PASTE: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());
    action.validate()?;
    if matches!(action, Action::Paste { .. }) {
        let permit = PASTE.lock().await;
        authorize(action)?;
        let action = action.clone();
        // Once the adapter takes ownership of the pasteboard it must finish restoring
        // it even if the originating UI or agent request is cancelled.
        return tokio::spawn(async move {
            let _permit = permit;
            backend.perform(&action).await
        })
        .await?;
    }
    authorize(action)?;
    backend.perform(action).await
}

pub struct SystemActions;

#[cfg(not(target_os = "macos"))]
#[async_trait]
impl DesktopActions for SystemActions {
    async fn perform(&self, _: &Action) -> Result<Value> {
        anyhow::bail!("System desktop actions require macOS")
    }
}

const BLOCKED_SCHEMES: &[&str] = &[
    "javascript",
    "data",
    "file",
    "shortcuts",
    "applescript",
    "help",
    "x-help-script",
    "x-man-page",
    "itms-services",
    "smb",
    "cifs",
    "afp",
    "nfs",
    "ftp",
    "ftps",
    "sftp",
    "ssh",
    "telnet",
    "vnc",
    "rdp",
    "tel",
    "facetime",
    "facetime-audio",
];

#[cfg(target_os = "macos")]
#[async_trait]
impl DesktopActions for SystemActions {
    async fn perform(&self, action: &Action) -> Result<Value> {
        use anyhow::{Context, bail};
        use std::time::Duration;
        use tokio::io::AsyncWriteExt;
        action.validate()?;
        // No shell, interpolation, user-supplied source, or unrestricted execution.
        let output = tokio::time::timeout(Duration::from_secs(300), async {
            let mut child = tokio::process::Command::new("/usr/bin/osascript")
                .env_clear()
                .envs(
                    ["HOME", "TMPDIR", "LANG", "LC_ALL", "USER", "LOGNAME"]
                        .into_iter()
                        .filter_map(|name| std::env::var_os(name).map(|v| (name, v))),
                )
                .args(["-l", "JavaScript", "-e", include_str!("native_os.js")])
                .stdin(std::process::Stdio::piped())
                .stdout(std::process::Stdio::piped())
                .stderr(std::process::Stdio::piped())
                .kill_on_drop(true)
                .spawn()?;
            // User text travels over stdin, never the process argument list.
            {
                let mut stdin = child.stdin.take().context("Native input unavailable")?;
                stdin.write_all(&serde_json::to_vec(action)?).await?;
            }
            anyhow::Ok(child.wait_with_output().await?)
        })
        .await
        .context("Native dialog timed out")??;
        if !output.status.success() {
            bail!(
                "Native operation failed: {}",
                String::from_utf8_lossy(&output.stderr)
            );
        }
        let result: Value =
            serde_json::from_slice(&output.stdout).context("Invalid native response")?;
        if result["ok"] != true {
            bail!(
                "{}",
                result["error"]
                    .as_str()
                    .unwrap_or("Native operation failed")
            );
        }
        Ok(result["value"].clone())
    }
}
