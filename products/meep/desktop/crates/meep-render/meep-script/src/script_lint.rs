//! The design checker for script views. It reads the rendered element tree
//! (never source text) and reports what the agent guides forbid.
//!
//! Errors reject an install or edit: they are mistakes no design calls for,
//! such as a drag with no keyboard path. Warnings are reported to the agent
//! and count against the view's grade. The SDK stays fully capable; this is
//! where quality is enforced.
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub enum Severity {
    Error,
    Warning,
}

#[derive(Clone, Debug)]
pub struct Finding {
    pub rule: &'static str,
    pub severity: Severity,
    pub message: String,
    /// The element's `id`, or its type when it has none.
    pub at: String,
}

/// DESIGN.md's spacing scale, plus 2 and 6 for hairline and label gaps and
/// 18 between form fields.
const SPACING: [f64; 14] = [
    0., 2., 4., 6., 8., 12., 16., 18., 20., 24., 32., 40., 48., 64.,
];
const RADII: [f64; 7] = [0., 2., 4., 6., 8., 12., 999.];
const TEXT: [&str; 7] = [
    "text", "heading", "caption", "mono", "label", "badge", "link",
];
/// Handlers added with the interaction SDK: held to the strict naming rule.
const POINTER: [&str; 4] = ["onPress", "onDoubleClick", "drag", "onNudge"];
const HANDLERS: [&str; 12] = [
    "onClick",
    "onDoubleClick",
    "onPress",
    "onRelease",
    "onHover",
    "onPointerMove",
    "onNudge",
    "onDrop",
    "onDragEnd",
    "onChange",
    "onSubmit",
    "onAction",
];

struct Walk<'a> {
    findings: Vec<Finding>,
    sizes: BTreeSet<String>,
    nodes: usize,
    pointer_moves: usize,
    palette: &'a dyn Fn(&str) -> Option<u32>,
}

impl Walk<'_> {
    fn add(
        &mut self,
        rule: &'static str,
        severity: Severity,
        node: &Value,
        message: impl Into<String>,
    ) {
        self.findings.push(Finding {
            rule,
            severity,
            message: message.into(),
            at: name(node),
        });
    }

    fn visit(
        &mut self,
        node: &Value,
        depth: usize,
        bg: Option<u32>,
        bg_literal: bool,
        in_group: bool,
        floating: bool,
    ) {
        self.nodes += 1;
        let p = &node["p"];
        let t = node["t"].as_str().unwrap_or("");
        if depth == 31 {
            self.add(
                "depth",
                Severity::Warning,
                node,
                "The tree nests more than 30 levels. Flatten wrappers that add no layout.",
            );
        }
        let has = |k: &str| p.get(k).is_some_and(|v| !v.is_null());
        let handles = HANDLERS.iter().any(|k| has(k)) || has("drag") || has("drop");
        let named = p["label"].as_str().is_some_and(|l| !l.trim().is_empty()) || has_text(node);

        // Interaction: everything clickable has a name; everything draggable
        // has a keyboard path.
        if has("drag") && !has("onNudge") {
            self.add("drag-keyboard", Severity::Error, node,
                "A draggable element needs onNudge({ dir, big }) so it can be moved with arrow keys. Every drag needs a keyboard path.");
        }
        if POINTER.iter().any(|k| has(k)) && !named {
            self.add("unnamed-control", Severity::Error, node,
                "This interactive element has no text and no `label`. Add `label` so VoiceOver and the agent can name it.");
        } else if has("onClick") && !TEXT.contains(&t) && !named {
            self.add("unnamed-click", Severity::Warning, node,
                "A clickable container with no text and no `label`. Add `label` with its accessible name.");
        }
        if t == "scene" {
            if !p["label"].as_str().is_some_and(|l| !l.trim().is_empty()) {
                self.add("unnamed-control", Severity::Error, node,
                    "A Scene needs `label`: what it shows (\"Dependency graph\"), for VoiceOver and the agent.");
            }
            if !has("h") && p["grow"] != true && !has("aspect") {
                self.add("scene-height", Severity::Warning, node,
                    "A Scene draws into the space it is given. Give it `h`, `grow: true` or `aspect`.");
            }
        }
        if t == "chart" {
            if !p["label"].as_str().is_some_and(|l| !l.trim().is_empty()) {
                self.add("unnamed-control", Severity::Error, node,
                    "A Chart needs `label`: what it measures (\"Signups per day\"), for its tooltip, VoiceOver and the agent.");
            }
            if p["data"].as_array().is_some_and(|d| d.len() > 5_000) {
                self.add("chart-size", Severity::Warning, node,
                    "A Chart draws at most 5,000 points. Aggregate first (per day, per week), or use a Scene for raw point clouds.");
            }
        }
        // Native components with no visible text of their own.
        if (t == "slider" || t == "rating")
            && !p["label"].as_str().is_some_and(|l| !l.trim().is_empty())
        {
            self.add(
                "unnamed-control",
                Severity::Error,
                node,
                format!(
                    "A {t} needs `label`, its accessible name (\"Volume\", \"Rating for this PR\")."
                ),
            );
        }
        if t == "hover_card"
            && node["c"]
                .as_array()
                .is_some_and(|c| c.iter().skip(1).any(has_handler))
        {
            self.add("hover-card-actions", Severity::Warning, node,
                "Controls inside a hover card vanish when the pointer leaves and can't be reached by keyboard. Hover cards preview; put actions in a Popover.");
        }
        if t == "popover" && p["open"].is_boolean() && !has("onOpenChange") {
            self.add("popover-stuck", Severity::Warning, node,
                "A popover with `open` but no `onOpenChange` can't be closed by Escape or a click outside.");
        }
        let feedback = has("hover") || has("hoverBg") || has("active") || p["cursor"] == "pointer";
        if feedback && !handles && !in_group && !has("tooltip") {
            self.add("inert-feedback", Severity::Warning, node,
                "Hover, press or pointer-cursor styling on something that does nothing when used. Feedback promises an action.");
        }
        if has("groupHover") && !in_group {
            self.add(
                "orphan-group-hover",
                Severity::Warning,
                node,
                "groupHover names a group no ancestor declares with `group`.",
            );
        }
        if p["onPointerMove"].is_object() {
            self.pointer_moves += 1;
        }

        // Layers and elevation.
        let layered = has("layer") || p["position"] == "absolute";
        if let Some(layer) = p["layer"].as_u64().filter(|l| *l > 3) {
            self.add("layer-depth", Severity::Error, node,
                format!("layer {layer}: there are three layers (1 popover, 2 sheet, 3 modal). Deeper stacks hide what's beneath."));
        }
        // A layer paints above the view but still takes its place in layout:
        // a sheet in flow squeezes everything beside it when it opens, and the
        // content jumps back when it closes.
        if p["layer"].as_u64().is_some_and(|l| l >= 2) && p["position"] != "absolute" {
            self.add("layer-in-flow", Severity::Warning, node,
                "A sheet or dialog (layer 2 or 3) in normal flow takes space from the rest of the view: opening it squeezes the content and closing it makes the content jump back. Give it position: \"absolute\" and anchors (a bottom sheet: left: 0, right: 0, bottom: 0).");
        }
        if has("shadow") && p["shadow"] != "none" && !layered && !floating {
            self.add("decorative-shadow", Severity::Warning, node,
                "A shadow on an element in normal flow. Shadows mark floating surfaces (layers, absolute overlays); separate regions with rules and spacing.");
        }
        if p["position"] == "absolute"
            && !["top", "right", "bottom", "left", "inset"]
                .iter()
                .any(|k| has(k))
        {
            self.add("unanchored", Severity::Warning, node,
                "position: \"absolute\" without top/right/bottom/left/inset lands wherever layout leaves it. Anchor it.");
        }

        // Type.
        // Icon sizes are not type.
        if let Some(size) = p["size"].as_f64().filter(|_| t != "icon") {
            self.sizes.insert(format!("{size}"));
            if size < 10. {
                self.add("tiny-text", Severity::Error, node,
                    format!("Text at {size} px is unreadable. The smallest size is 11 px (`caption`, small labels)."));
            }
        }

        // Spacing and shape on the scale.
        for key in [
            "gap", "p", "px", "py", "pt", "pb", "pl", "pr", "mt", "mb", "ml", "mr",
        ] {
            if let Some(v) = p[key].as_f64()
                && !SPACING.contains(&v.abs())
            {
                self.add("off-scale-spacing", Severity::Warning, node,
                    format!("{key}: {v} is off the spacing scale (4, 8, 12, 16, 20, 24, 32, 40, 48, 64; 2 and 6 for tight gaps, 18 between form fields)."));
            }
        }
        if let Some(r) = p["radius"].as_f64()
            && !RADII.contains(&r)
        {
            self.add(
                "off-scale-radius",
                Severity::Warning,
                node,
                format!(
                    "radius {r}: use 6 (controls), 8 (surfaces), 4 (small marks) or 999 (pills)."
                ),
            );
        }

        // Colour: theme tokens, readable contrast.
        // `data: true` marks a literal as a deliberate data or brand colour
        // (a chart series, a language swatch), which the guide permits.
        for key in ["bg", "color", "borderColor", "hoverBg"] {
            if p["data"] != true && p[key].as_str().is_some_and(|s| s.starts_with('#')) {
                self.add("literal-color", Severity::Warning, node,
                    format!("A literal {key} color. Use a theme token (ink, secondary, inset, accent, ...) so it follows Settings → Appearance. A deliberate data or brand colour takes `data: true`."));
            }
        }
        let own_bg = p["bg"].as_str().and_then(|c| (self.palette)(c)).or(bg);
        let literal_bg = p["bg"]
            .as_str()
            .map(|c| c.starts_with('#'))
            .unwrap_or(bg_literal);
        // Token pairs are the theme's contrast, not the view's; among tokens
        // only `tertiary` (decorative by definition) is wrong for text.
        let fg_name = p["color"].as_str().unwrap_or("");
        let judged = fg_name.starts_with('#') || literal_bg || fg_name == "tertiary";
        if TEXT.contains(&t)
            && judged
            && let (Some(fg), Some(back)) = ((self.palette)(fg_name), own_bg)
        {
            let ratio = contrast(fg, back);
            let large = p["size"].as_f64().unwrap_or(13.) >= 18.;
            let needed = if large { 3. } else { 4.5 };
            if ratio < needed {
                self.add(
                    "contrast",
                    Severity::Warning,
                    node,
                    format!("Text contrast {ratio:.1}:1 against its background; needs {needed}:1."),
                );
            }
        }

        // Motion: short for interface, loops only where they mean something.
        let motion = &p["motion"];
        if motion.is_object() {
            let transition = &motion["transition"];
            let looping = transition["repeat"] == "infinite";
            if looping && t != "icon" && p["role"] != "status" {
                self.add("motion-loop", Severity::Warning, node,
                    "An infinite animation on content or chrome. Loops belong to live indicators (an Icon, or role: \"status\").");
            }
            if motion["keyframes"].is_null()
                && transition["duration"].as_f64().is_some_and(|d| d > 300.)
            {
                self.add(
                    "motion-slow",
                    Severity::Warning,
                    node,
                    "Interface motion over 300 ms feels sluggish. Use 120-240 ms.",
                );
            }
            if transition["type"] == "spring"
                && transition["damping"].as_f64().is_some_and(|d| d < 0.7)
            {
                self.add("motion-bounce", Severity::Warning, node,
                    "A spring with damping below 0.7 bounces visibly. Interface springs are critically damped (1).");
            }
        }

        let group = in_group || has("group");
        for child in node["c"].as_array().into_iter().flatten() {
            self.visit(
                child,
                depth + 1,
                own_bg,
                literal_bg,
                group,
                floating || layered,
            );
        }
    }
}

/// Where a finding is: the element's `id`, else its type and the start of
/// its text, so it can be found in the source.
fn name(node: &Value) -> String {
    if let Some(id) = node["p"]["id"].as_str() {
        return format!("#{id}");
    }
    let t = node["t"].as_str().unwrap_or("element");
    let text = ["text", "label", "title", "name"]
        .iter()
        .find_map(|k| node["p"][*k].as_str().filter(|s| !s.trim().is_empty()))
        .or_else(|| {
            node["c"]
                .as_array()?
                .iter()
                .find_map(|c| c["p"]["text"].as_str())
        });
    match text {
        Some(text) => {
            let short: String = text.chars().take(32).collect();
            format!("{t} \"{short}\"")
        }
        None => t.to_owned(),
    }
}

/// Any handler on this element or below.
fn has_handler(node: &Value) -> bool {
    node["p"]
        .as_object()
        .is_some_and(|p| p.values().any(|v| v.get("$fn").is_some()))
        || node["c"].as_array().into_iter().flatten().any(has_handler)
}

/// Text anywhere inside: what a screen reader would read as the name.
fn has_text(node: &Value) -> bool {
    let p = &node["p"];
    ["text", "label", "title"]
        .iter()
        .any(|k| p[*k].as_str().is_some_and(|s| !s.trim().is_empty()))
        || node["c"].as_array().into_iter().flatten().any(has_text)
}

fn luminance(rgb: u32) -> f64 {
    let channel = |shift: u32| {
        let c = ((rgb >> shift) & 0xff) as f64 / 255.;
        if c <= 0.03928 {
            c / 12.92
        } else {
            ((c + 0.055) / 1.055).powf(2.4)
        }
    };
    0.2126 * channel(16) + 0.7152 * channel(8) + 0.0722 * channel(0)
}

/// WCAG contrast ratio between two opaque colours.
pub fn contrast(a: u32, b: u32) -> f64 {
    let (la, lb) = (luminance(a), luminance(b));
    (la.max(lb) + 0.05) / (la.min(lb) + 0.05)
}

/// Resolves a token or `#rrggbb` to an opaque colour in the current palette.
pub fn resolve(color: &str) -> Option<u32> {
    if let Some(hex) = color.strip_prefix('#') {
        return match hex.len() {
            6 => u32::from_str_radix(hex, 16).ok(),
            // Translucent literals can't be judged without compositing.
            _ => None,
        };
    }
    let name = if color == "background" {
        "canvas"
    } else {
        color
    };
    crate::theme::named(name)
}

/// Checks a rendered tree.
pub fn check(tree: &Value) -> Vec<Finding> {
    let mut walk = Walk {
        findings: Vec::new(),
        sizes: BTreeSet::new(),
        nodes: 0,
        pointer_moves: 0,
        palette: &resolve,
    };
    let canvas = crate::theme::named("canvas");
    walk.visit(tree, 0, canvas, false, false, false);
    if walk.sizes.len() > 5 {
        let sizes: Vec<_> = walk.sizes.iter().cloned().collect();
        walk.add("type-sizes", Severity::Warning, tree, format!(
            "{} text sizes ({}). A view needs at most five: title, body, secondary, mono and small.",
            sizes.len(), sizes.join(", ")));
    }
    if walk.nodes > 1500 {
        walk.add("tree-size", Severity::Warning, tree, format!(
            "{} elements rendered at once. Use List for anything that grows; it renders only visible rows.", walk.nodes));
    }
    if walk.pointer_moves > 20 {
        walk.add("pointer-move-many", Severity::Warning, tree,
            "onPointerMove on more than 20 elements. Put one on the shared container and compute what's under the pointer.");
    }
    walk.findings
}

/// One finding per rule and element, errors first.
pub fn dedupe(findings: Vec<Finding>) -> Vec<Finding> {
    let mut seen = BTreeSet::new();
    let mut out: Vec<Finding> = findings
        .into_iter()
        .filter(|f| seen.insert((f.rule, f.at.clone())))
        .collect();
    out.sort_by_key(|f| f.severity);
    out
}

/// A 0-100 score: errors cost 12 and warnings 3, each rule counted at most
/// three times so one repeated pattern doesn't sink an otherwise good view.
pub fn grade(findings: &[Finding]) -> (u32, char) {
    let mut per_rule: BTreeMap<&str, (Severity, u32)> = BTreeMap::new();
    for f in findings {
        let entry = per_rule.entry(f.rule).or_insert((f.severity, 0));
        entry.1 += 1;
    }
    let cost: u32 = per_rule
        .values()
        .map(|(severity, n)| n.min(&3) * if *severity == Severity::Error { 12 } else { 3 })
        .sum();
    let score = 100u32.saturating_sub(cost);
    let letter = match score {
        90.. => 'A',
        80..=89 => 'B',
        70..=79 => 'C',
        60..=69 => 'D',
        _ => 'F',
    };
    (score, letter)
}

pub fn to_json(findings: &[Finding]) -> Value {
    json!(
        findings
            .iter()
            .map(|f| json!({
                "rule": f.rule,
                "severity": if f.severity == Severity::Error { "error" } else { "warning" },
                "at": f.at,
                "message": f.message,
            }))
            .collect::<Vec<_>>()
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tree(p: Value, children: Vec<Value>) -> Value {
        json!({"t": "box", "p": p, "c": children})
    }
    fn text(s: &str) -> Value {
        json!({"t": "text", "p": {"text": s}, "c": []})
    }
    fn rules(t: &Value) -> Vec<&'static str> {
        check(t).into_iter().map(|f| f.rule).collect()
    }

    #[::core::prelude::v1::test]
    fn drag_needs_a_keyboard_path_and_a_name() {
        let f = json!({"$fn": 1});
        let bare = tree(json!({"drag": {"type": "card"}, "onDragEnd": f}), vec![]);
        let r = rules(&bare);
        assert!(r.contains(&"drag-keyboard") && r.contains(&"unnamed-control"));
        let good = tree(
            json!({"drag": {"type": "card"}, "onNudge": f, "label": "Card"}),
            vec![],
        );
        assert!(check(&good).iter().all(|f| f.severity != Severity::Error));
        let named_by_text = tree(json!({"drag": {}, "onNudge": f}), vec![text("Move me")]);
        assert!(!rules(&named_by_text).contains(&"unnamed-control"));
    }

    #[::core::prelude::v1::test]
    fn scale_type_and_shadows_follow_the_design_guide() {
        let t = tree(
            json!({"gap": 7, "radius": 5, "shadow": "md"}),
            vec![json!({"t": "text", "p": {"text": "x", "size": 9}, "c": []})],
        );
        let r = rules(&t);
        for rule in [
            "off-scale-spacing",
            "off-scale-radius",
            "decorative-shadow",
            "tiny-text",
        ] {
            assert!(r.contains(&rule), "{rule} missing from {r:?}");
        }
        let floating = tree(
            json!({"layer": 1, "shadow": "md", "gap": 8, "radius": 8}),
            vec![text("Menu")],
        );
        assert!(rules(&floating).is_empty(), "{:?}", rules(&floating));
    }

    #[::core::prelude::v1::test]
    fn sheets_float_out_of_the_layout() {
        let in_flow = tree(json!({"layer": 2, "h": "72%", "shadow": "lg"}), vec![]);
        assert!(rules(&in_flow).contains(&"layer-in-flow"));
        let floating = tree(
            json!({"layer": 2, "position": "absolute", "left": 0, "right": 0, "bottom": 0, "h": "72%"}),
            vec![],
        );
        assert!(!rules(&floating).contains(&"layer-in-flow"));
    }

    #[::core::prelude::v1::test]
    fn token_pairs_are_the_themes_contrast_except_tertiary_text() {
        let on = |color: &str| {
            tree(
                json!({"bg": "inset"}),
                vec![json!({"t": "text", "p": {"text": "x", "color": color}, "c": []})],
            )
        };
        assert!(!rules(&on("orange")).contains(&"contrast"));
        assert!(rules(&on("tertiary")).contains(&"contrast"));
    }

    #[::core::prelude::v1::test]
    fn feedback_without_an_action_and_low_contrast_warn() {
        let t = tree(
            json!({"hover": {"bg": "inset"}, "bg": "canvas"}),
            vec![json!({"t": "text", "p": {"text": "faint", "color": "#eeeeee"}, "c": []})],
        );
        let r = rules(&t);
        assert!(
            r.contains(&"inert-feedback") && r.contains(&"contrast"),
            "{r:?}"
        );
    }

    #[::core::prelude::v1::test]
    fn grades_cap_repeated_rules() {
        let warn = |rule| Finding {
            rule,
            severity: Severity::Warning,
            message: String::new(),
            at: String::new(),
        };
        assert_eq!(grade(&[]), (100, 'A'));
        let many: Vec<_> = (0..20).map(|_| warn("off-scale-spacing")).collect();
        assert_eq!(grade(&many), (91, 'A'));
        let error = Finding {
            severity: Severity::Error,
            ..warn("drag-keyboard")
        };
        assert_eq!(grade(&[error.clone(), error.clone(), error]).0, 64);
    }
}
