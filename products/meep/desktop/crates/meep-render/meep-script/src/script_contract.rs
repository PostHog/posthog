//! Element names and structural validation shared by both script engines.
use serde_json::Value;
/// Element types the host knows how to render.
/// Every component element name, for `script::ELEMENTS`.
pub const COMPONENTS: [&str; 18] = [
    "scene",
    "chart",
    "model_selector",
    "markdown",
    "hover_card",
    "popover",
    "radio_group",
    "rating",
    "kbd",
    "tag",
    "skeleton",
    "spinner",
    "description_list",
    "pagination",
    "accordion",
    "breadcrumb",
    "slider",
    "avatar",
];

pub const ELEMENTS: &[&str] = &[
    "page",
    "column",
    "row",
    "box",
    "scroll",
    "card",
    "text",
    "heading",
    "caption",
    "mono",
    "label",
    "badge",
    "icon",
    "logo",
    "image",
    "button",
    "icon_button",
    "input",
    "checkbox",
    "divider",
    "spacer",
    "header",
    "empty",
    "loading",
    "error",
    "notice",
    "list",
    "table",
    "form",
    "field",
    "actions",
    "section",
    "link",
    "read_only",
    "textarea",
    "toggle",
    "select",
    "tabs",
    "progress",
    "list_row",
    "reading",
    "date_picker",
    "time_picker",
    "action_menu",
    "context_menu",
    "reveal",
    "block_editor",
    "workflow_outline",
    "workflow_editor",
];

/// Check unknown element types before a tree reaches the renderer.
pub fn check_tree(node: &Value) -> Result<(), String> {
    let kind = node["t"].as_str().unwrap_or("");
    if !ELEMENTS.contains(&kind) && !COMPONENTS.contains(&kind) {
        return Err(format!(
            "Unknown element \"{kind}\". Use one of: {}",
            ELEMENTS
                .iter()
                .chain(COMPONENTS.iter())
                .copied()
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    node["c"]
        .as_array()
        .into_iter()
        .flatten()
        .try_for_each(check_tree)
}

/// A concise presentation for shell notices; full diagnostics still reach the agent.
pub fn diagnostic_summary(error: &str) -> String {
    let main = error.lines().next().unwrap_or(error);
    let location = error.find("view.js:").map(|at| {
        error[at..]
            .chars()
            .take_while(|c| c.is_ascii_alphanumeric() || ".:".contains(*c))
            .collect::<String>()
    });
    match location {
        Some(at) if !main.contains(&at) => format!("{main} ({at})"),
        _ => main.to_owned(),
    }
}
