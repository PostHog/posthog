#[derive(Debug, Clone)]
pub struct Group {
    pub id: i64,
    pub team_id: i64,
    pub group_type_index: i32,
    pub group_key: String,
    pub group_properties: serde_json::Value,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub properties_last_updated_at: Option<serde_json::Value>,
    pub properties_last_operation: Option<serde_json::Value>,
    pub version: i64,
}

#[derive(Debug, Clone)]
pub struct GroupTypeMapping {
    pub id: i64,
    pub team_id: i64,
    pub project_id: i64,
    pub group_type: String,
    pub group_type_index: i32,
    pub name_singular: Option<String>,
    pub name_plural: Option<String>,
    pub default_columns: Option<serde_json::Value>,
    pub detail_dashboard_id: Option<i64>,
    pub created_at: Option<chrono::DateTime<chrono::Utc>>,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct GroupIdentifier {
    pub group_type_index: i32,
    pub group_key: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct GroupKey {
    pub team_id: i64,
    pub group_type_index: i32,
    pub group_key: String,
}
