use chrono::{DateTime, Local, Utc};
use serde::Deserialize;

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct HogMessage {
    pub id: String,
    pub author: String,
    pub content: String,
    pub created_at: DateTime<Utc>,
    pub delivered_at: Option<DateTime<Utc>>,
    pub seen_at: Option<DateTime<Utc>>,
    pub read_at: Option<DateTime<Utc>>,
    pub report: Option<HogReport>,
    pub action: Option<HogAction>,
}

impl HogMessage {
    pub fn from_owner(&self) -> bool {
        self.author == "user"
    }

    pub fn is_system(&self) -> bool {
        self.author == "system"
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct Hog {
    pub id: String,
    pub name: String,
    pub emoji: String,
    pub color: String,
    pub responsibility: String,
    pub memory: String,
    pub status: String,
    pub mcp_installation_ids: Vec<String>,
    pub working: bool,
    pub unread_count: u32,
    pub needs_you_count: u32,
    pub last_message: Option<HogMessage>,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct HogSchedule {
    pub id: String,
    pub prompt: String,
    pub cron_expression: Option<String>,
    pub next_fire_at: Option<DateTime<Utc>>,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct Evidence {
    pub description: String,
    pub source: String,
    pub kind: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct HogReport {
    pub id: String,
    pub title: String,
    pub summary: String,
    pub priority: String,
    pub impact: String,
    pub proposal: String,
    pub evidence: Vec<Evidence>,
    pub status: String,
    pub follow_up: Option<String>,
}

impl HogReport {
    /// True until the owner resolves, dismisses or follows up on the report.
    pub fn waiting(&self) -> bool {
        self.status == "open" && self.follow_up.is_none()
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct HogAction {
    pub id: String,
    pub kind: String,
    pub label: String,
    pub draft: String,
    pub status: String,
    pub result: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct HogTrigger {
    pub id: String,
    pub name: String,
    pub fire_path: String,
    pub fire_count: u32,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct HogRule {
    pub id: String,
    pub kind: String,
    pub effect: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct McpInstallation {
    pub id: String,
    pub name: Option<String>,
    pub display_name: Option<String>,
    pub url: Option<String>,
    pub description: Option<String>,
}

impl McpInstallation {
    pub fn title(&self) -> String {
        self.display_name
            .clone()
            .or_else(|| self.name.clone())
            .or_else(|| self.url.clone())
            .unwrap_or_else(|| "MCP server".into())
    }
}

#[derive(Clone, Debug, Deserialize)]
pub struct Team {
    pub id: i64,
    pub name: String,
}

#[derive(Clone, Debug, Deserialize)]
pub struct Me {
    pub email: String,
    pub team: Option<Team>,
}

pub fn time_label(at: &DateTime<Utc>) -> String {
    at.with_timezone(&Local).format("%-I:%M %p").to_string()
}

pub fn day_label(at: &DateTime<Utc>) -> String {
    let day = at.with_timezone(&Local).date_naive();
    let today = Local::now().date_naive();
    match (today - day).num_days() {
        0 => "Today".into(),
        1 => "Yesterday".into(),
        _ => day.format("%-d %B %Y").to_string(),
    }
}

pub fn list_label(at: &DateTime<Utc>) -> String {
    let day = at.with_timezone(&Local).date_naive();
    match (Local::now().date_naive() - day).num_days() {
        0 => time_label(at),
        1 => "Yesterday".into(),
        _ => day.format("%-d %b").to_string(),
    }
}

pub fn same_day(a: &DateTime<Utc>, b: &DateTime<Utc>) -> bool {
    a.with_timezone(&Local).date_naive() == b.with_timezone(&Local).date_naive()
}
