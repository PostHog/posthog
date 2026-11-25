//! Bundled agent artwork for native pickers and their selected values.
use gpui_kit::{assets::IconName, component::Icon, *};
use std::sync::{Arc, OnceLock};

pub struct AgentMark {
    pub name: &'static str,
    png: &'static [u8],
    image: OnceLock<Arc<Image>>,
}

macro_rules! mark {
    ($name:literal) => {
        AgentMark {
            name: $name,
            png: include_bytes!(concat!("../assets/agents/", $name, "-mark.png")),
            image: OnceLock::new(),
        }
    };
}

static MARKS: [AgentMark; 9] = [
    mark!("claude"),
    mark!("codex"),
    mark!("opencode"),
    mark!("gemini"),
    mark!("cursor"),
    mark!("copilot"),
    mark!("droid"),
    mark!("pi"),
    mark!("fx"),
];

pub fn named(name: &str) -> Option<&'static AgentMark> {
    MARKS
        .iter()
        .find(|mark| mark.name.eq_ignore_ascii_case(name))
}

/// Prefer a catalogue's runtime, including when it has no artwork. A model ID
/// can also arrive on its own, for instance when restoring a saved selection.
pub fn for_model(runtime: Option<&str>, id: &str) -> Option<&'static AgentMark> {
    if let Some(runtime) = runtime.filter(|name| !name.is_empty()) {
        return named(runtime);
    }
    let (namespace, model) = id.split_once('/').unwrap_or(("", id));
    let family = model.split('-').next().unwrap_or(model);
    match namespace {
        "anthropic" => named("claude"),
        "openai" => named("codex"),
        "google" if family == "gemini" => named("gemini"),
        "" if family == "gpt" => named("codex"),
        "" => named(family),
        agent => named(agent),
    }
}

pub fn icon(mark: Option<&AgentMark>, size: f32) -> AnyElement {
    let Some(mark) = mark else {
        return Icon::new(IconName::Cpu)
            .size(px(size))
            .flex_none()
            .into_any_element();
    };
    let image = mark
        .image
        .get_or_init(|| Arc::new(Image::from_bytes(ImageFormat::Png, mark.png.to_vec())));
    img(image.clone())
        .size(px(size))
        .flex_none()
        .into_any_element()
}

#[cfg(test)]
mod tests {
    use super::for_model;
    #[test]
    fn catalogue_runtime_takes_precedence_over_model_family() {
        for (runtime, id, expected) in [
            (Some("claude"), "zai-org/glm-5.3", Some("claude")),
            (Some("future-runtime"), "gpt-5.5", None),
            (None, "anthropic/sonnet", Some("claude")),
            (None, "claude-opus-4-8", Some("claude")),
            (None, "openai/gpt-5.5", Some("codex")),
            (None, "gpt-5.5", Some("codex")),
            (None, "google/gemini-3", Some("gemini")),
            (None, "zai-org/glm-5.3", None),
            (None, "", None),
        ] {
            assert_eq!(
                for_model(runtime, id).map(|m| m.name),
                expected,
                "{runtime:?} {id}"
            );
        }
    }
}
