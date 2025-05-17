#[derive(Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct LinksRedisItem {
    pub url: String,
    pub team_id: Option<i32>,
}

#[derive(Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ClickHouseEventProperties {
    pub current_url: String,
    pub ip: Option<String>,
    pub user_agent: Option<String>,
}
