use serde::{Deserialize, Serialize};
/// Persisted, host-normalized sidebar content. Commands remain view-owned.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct SidebarCard {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub items: Vec<SidebarCardItem>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct SidebarCardItem {
    pub label: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub marker: Option<SidebarMarker>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub command: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub args: Option<serde_json::Value>,
}
/// Small decorative marks; the host owns their geometry and palette.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct SidebarMarker {
    pub shape: String,
    pub color: String,
}
impl SidebarCard {
    pub fn normalize(value: &serde_json::Value, commands: &[String]) -> Option<Self> {
        fn text(v: &serde_json::Value) -> Option<String> {
            let s: String = v.as_str()?.split_whitespace().collect::<Vec<_>>().join(" ");
            (!s.is_empty()).then_some(s)
        }
        let mut card = Self {
            title: text(&value["title"]),
            items: vec![],
        };
        for item in value["items"].as_array().into_iter().flatten() {
            let Some(label) = text(&item["label"]) else {
                continue;
            };
            let command = item["command"]
                .as_str()
                .filter(|s| commands.iter().any(|c| c == s))
                .map(str::to_owned);
            let args = command
                .as_ref()
                .and_then(|_| item.get("args"))
                .filter(|v| serde_json::to_vec(v).is_ok_and(|s| s.len() <= 1024))
                .cloned();
            card.items.push(SidebarCardItem {
                label,
                detail: text(&item["detail"]),
                marker: item.get("marker").and_then(|marker| {
                    let shape = marker["shape"].as_str()?;
                    let color = marker["color"].as_str().unwrap_or("secondary");
                    (matches!(
                        shape,
                        "circle" | "ring" | "square" | "rectangle" | "diamond" | "star"
                    ) && crate::theme::marker_color(color).is_some())
                    .then(|| SidebarMarker {
                        shape: shape.into(),
                        color: color.into(),
                    })
                }),
                command,
                args,
            });
        }
        (card.title.is_some() || !card.items.is_empty()).then_some(card)
    }
}
