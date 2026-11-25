//! Reading element props: identity, handlers, text, colors, lengths and
//! icons, and turning layout, color and type props into a GPUI style.
use super::*;

pub(super) fn handler(p: &Value, key: &str) -> Option<u32> {
    p[key]["$fn"].as_u64().map(|id| id as u32)
}
pub(super) fn text(p: &Value, key: &str) -> String {
    match &p[key] {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

pub(super) fn color(value: &Value) -> Option<Hsla> {
    let name = value.as_str()?;
    if let Some(color) = ui::theme::named(name) {
        return Some(rgb(color).into());
    }
    let token = match name {
        "ink" | "text" => Some(ui::INK),
        "secondary" | "muted" => Some(ui::SECONDARY),
        "tertiary" | "faint" => Some(ui::TERTIARY),
        "canvas" | "background" => Some(ui::CANVAS),
        "inset" | "subtle" => Some(ui::INSET),
        "rule" | "border" => Some(ui::RULE),
        "chrome" => Some(ui::CHROME),
        "selected" => Some(ui::SELECTED),
        "danger" | "red" => Some(ui::DANGER),
        "positive" | "green" => Some(ui::POSITIVE),
        "accent" | "blue" => Some(0x0a66d8),
        "orange" => Some(0xc2610c),
        "purple" => Some(0x7b45c4),
        _ => None,
    };
    if let Some(token) = token {
        return Some(rgb(ui::theme::color(token)).into());
    }
    let hex = name.strip_prefix('#')?;
    let parsed = u32::from_str_radix(hex, 16).ok()?;
    match hex.len() {
        3 => {
            let (r, g, b) = ((parsed >> 8) & 0xf, (parsed >> 4) & 0xf, parsed & 0xf);
            Some(rgb(((r * 0x11) << 16) | ((g * 0x11) << 8) | (b * 0x11)).into())
        }
        6 => Some(rgb(parsed).into()),
        8 => Some(rgba(parsed).into()),
        _ => None,
    }
}
pub(super) fn length(value: &Value) -> Option<Length> {
    if let Some(n) = value.as_f64() {
        return Some(px(n as f32).into());
    }
    match value.as_str()? {
        "full" | "fill" => Some(relative(1.).into()),
        "auto" => Some(Length::Auto),
        s => s
            .strip_suffix('%')
            .and_then(|n| n.parse::<f32>().ok())
            .map(|n| relative(n / 100.).into()),
    }
}
pub(super) fn number(p: &Value, key: &str) -> Option<Pixels> {
    p[key].as_f64().map(|n| px(n as f32))
}
pub(super) fn icon_name(name: &str) -> IconName {
    // Built once: scanning every icon per element showed up in frame profiles.
    static BY_NAME: std::sync::OnceLock<HashMap<String, IconName>> = std::sync::OnceLock::new();
    let by_name = BY_NAME.get_or_init(|| {
        IconName::ALL
            .iter()
            .filter_map(|icon| {
                let path = icon.path();
                let name = path.strip_prefix("icons/")?.strip_suffix(".svg")?;
                Some((name.to_owned(), *icon))
            })
            .collect()
    });
    // Lucide names the bundle spells differently.
    let name = match name {
        "trash-2" => "trash",
        other => other,
    };
    by_name.get(name).copied().unwrap_or(IconName::CircleAlert)
}

thread_local! {
    /// The motion frame for the element being built. Set by `Build::node`,
    /// consumed by that element's own `style` call, so motion applies to the
    /// element itself rather than to a wrapper that would change its layout.
    pub(super) static MOTION: std::cell::Cell<Option<crate::script_motion::Frame>> =
        const { std::cell::Cell::new(None) };
}

/// Layout, color and type props shared by every box-like element, resolved
/// when the tree was parsed (see `styles`), then the element's motion frame.
pub(super) fn style<E: Styled>(mut e: E, node: &Node) -> E {
    e.style().refine(&node.style.refinement);
    // Motion paints over the static style for the properties it animates.
    if let Some(frame) = MOTION.with(|m| m.take()) {
        e = frame.apply(e, &node.p);
    }
    e
}

/// The props part of `style`: the same for given props until the palette
/// changes, so it is resolved once per tree (`styles::Memo`).
pub(super) fn static_style<E: Styled>(mut e: E, p: &Value) -> E {
    if let Some(v) = number(p, "gap") {
        e = e.gap(v);
    }
    for (key, apply) in [
        ("p", Styled::p as fn(E, DefiniteLength) -> E),
        ("px", Styled::px),
        ("py", Styled::py),
        ("pt", Styled::pt),
        ("pb", Styled::pb),
        ("pl", Styled::pl),
        ("pr", Styled::pr),
        ("mt", Styled::mt),
        ("mb", Styled::mb),
        ("ml", Styled::ml),
        ("mr", Styled::mr),
    ] {
        if let Some(v) = number(p, key) {
            e = apply(e, v.into());
        }
    }
    for (key, apply) in [
        ("w", Styled::w as fn(E, Length) -> E),
        ("h", Styled::h),
        ("minW", Styled::min_w),
        ("maxW", Styled::max_w),
        ("minH", Styled::min_h),
        ("maxH", Styled::max_h),
    ] {
        if let Some(v) = length(&p[key]) {
            e = apply(e, v);
        }
    }
    if p["grow"] == true {
        e = e.flex_1().min_w_0().min_h_0();
    }
    if p["shrink"] == false {
        e = e.flex_shrink_0();
    }
    e = match p["align"].as_str() {
        Some("start") => e.items_start(),
        Some("center") => e.items_center(),
        Some("end") => e.items_end(),
        Some("stretch") => e.items_stretch(),
        Some("baseline") => e.items_baseline(),
        _ => e,
    };
    e = match p["justify"].as_str() {
        Some("start") => e.justify_start(),
        Some("center") => e.justify_center(),
        Some("end") => e.justify_end(),
        Some("between") => e.justify_between(),
        Some("around") => e.justify_around(),
        _ => e,
    };
    if p["wrap"] == true {
        e = e.flex_wrap();
    }
    if let Some(c) = color(&p["bg"]) {
        e = e.bg(c);
    }
    if let Some(c) = color(&p["color"]) {
        e = e.text_color(c);
    }
    if let Some(r) = number(p, "radius") {
        e = e.rounded(r);
    }
    if let Some(c) = color(&p["borderColor"]) {
        e = e.border_color(c);
    }
    match &p["border"] {
        Value::Bool(true) => {
            e = e
                .border_1()
                .border_color(rgb(crate::sdk::ui::theme::color(ui::RULE)))
        }
        Value::String(side) => {
            e = match side.as_str() {
                "top" => e.border_t_1(),
                "bottom" => e.border_b_1(),
                "left" => e.border_l_1(),
                "right" => e.border_r_1(),
                _ => e.border_1(),
            };
            if p["borderColor"].is_null() {
                e = e.border_color(rgb(crate::sdk::ui::theme::color(ui::RULE)));
            }
        }
        _ => {}
    }
    if let Some(size) = number(p, "size") {
        e = e.text_size(size);
    }
    e = match p["weight"].as_str() {
        Some("normal") => e.font_weight(FontWeight::NORMAL),
        Some("medium") => e.font_weight(FontWeight::MEDIUM),
        Some("semibold") => e.font_weight(FontWeight::SEMIBOLD),
        Some("bold") => e.font_weight(FontWeight::BOLD),
        _ => e,
    };
    if p["font"] == "mono" {
        e = e.font_family(ui::mono_font());
    }
    if p["truncate"] == true {
        e = e.min_w_0().truncate();
    }
    if p["nowrap"] == true {
        e = e.whitespace_nowrap();
    }
    if let Some(o) = p["opacity"].as_f64() {
        e = e.opacity(o as f32);
    }
    if p["clip"] == true {
        e = e.overflow_hidden();
    }
    interact::layout(e, p)
}

/// The element each container kind starts from, before its props. Shared by
/// `Build::element` and the region analysis (`styles`), so both see the same
/// layout.
pub(super) fn container_base(kind: &str) -> Option<Div> {
    Some(match kind {
        "page" => ui::page(),
        "column" => ui::column(),
        "row" => ui::row(),
        "box" => div(),
        "reading" => ui::reading_column(),
        "card" => ui::surface().p(px(16.)).gap(px(8.)),
        "scroll" => div()
            .flex()
            .flex_col()
            .gap(px(8.))
            .w_full()
            .flex_1()
            .min_h_0(),
        _ => return None,
    })
}

#[cfg(test)]
mod theme_tests {
    use super::color;
    use crate::sdk::ui;
    use serde_json::json;

    #[test]
    fn theme_updates_resolve_existing_tokens_but_preserve_literals() {
        let token = json!("canvas");
        let literal = json!("#ffffff");
        let original = color(&token);
        let mut palette = ui::theme::DEFAULT;
        palette[3] = 0x121212;
        palette[13] = 0xeeeeee;
        ui::theme::set(palette);
        assert_ne!(color(&token), original);
        assert_eq!(color(&json!("background")), color(&token));
        assert_eq!(color(&literal), original);
        assert_eq!(
            color(&json!("accentForeground")),
            Some(gpui_kit::rgb(0xeeeeee).into())
        );
        ui::theme::set(ui::theme::DEFAULT);
    }
}
