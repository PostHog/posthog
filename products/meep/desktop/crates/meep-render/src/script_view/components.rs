//! gpui-kit components for script views, beyond the core controls.
//!
//! Each arm maps a script element onto the native component with the
//! smallest faithful surface: values in, one handler out. Overlays (hover
//! cards, popovers) build their content lazily, only while open. Nothing
//! here reaches outside the broker: avatars draw initials, never a URL.
use super::{Build, Node, color, handler, style, text};
use crate::sdk::ui;
use gpui_kit::assets::IconName;
use gpui_kit::component::Icon;
use gpui_kit::component::{
    Sizable,
    accordion::Accordion,
    avatar::Avatar,
    breadcrumb::{Breadcrumb, BreadcrumbItem},
    button::ButtonVariants as _,
    description_list::DescriptionList,
    hover_card::HoverCard,
    kbd::Kbd,
    pagination::Pagination,
    popover::Popover,
    radio::{Radio, RadioGroup},
    rating::Rating,
    skeleton::Skeleton,
    slider::{Slider, SliderEvent, SliderState, SliderValue},
    spinner::Spinner,
    tag::Tag,
};
use gpui_kit::*;
use serde_json::{Value, json};
use std::{borrow::Cow, cell::Cell, rc::Rc};

/// `items` as (value, label) pairs: strings, or `{ value, label }` objects.
fn options(p: &Value) -> Vec<(Value, String)> {
    p["items"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|item| match item {
            Value::Object(_) => {
                let label = text(item, "label");
                (item.get("value").cloned().unwrap_or(json!(label)), label)
            }
            other => (other.clone(), text(&json!({ "v": other }), "v")),
        })
        .collect()
}

/// A slider's native state and its event subscription, kept per element.
struct SliderSlot {
    state: Entity<SliderState>,
    /// The value the script last set, so only script changes move the thumb.
    applied: Cell<f32>,
    _events: Subscription,
}

impl Build {
    fn call(&self, handler: Option<u32>, argument: Value, cx: &mut App) {
        if let Some(h) = handler {
            let _ = self
                .weak
                .update(cx, |view, cx| view.invoke(h, argument, true, cx));
        }
    }

    /// A child subtree as an element, for overlay content built on demand.
    fn subtree(
        &self,
        nodes: Rc<Vec<Rc<Node>>>,
    ) -> impl Fn(&mut Window, &mut App) -> AnyElement + 'static {
        let build = self.clone();
        move |window, cx| {
            ui::column()
                .gap(px(8.))
                .children(nodes.iter().map(|node| build.node(node, window, cx)))
                .into_any_element()
        }
    }

    #[inline(never)]
    pub(super) fn component(
        &self,
        node: &Rc<Node>,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let p = &node.p;
        let key = node.key.to_string();
        let id = ElementId::Name(key.clone().into());
        let children = &node.children;
        let disabled = self.read_only || p["disabled"] == true;
        match node.kind {
            // A preview that opens while the pointer rests on its trigger.
            "hover_card" | "popover" => {
                let mut nodes = children.iter();
                // A popover's trigger is a button: its text is a label.
                let trigger_build = match node.kind {
                    "popover" => Cow::Owned(self.in_control()),
                    _ => Cow::Borrowed(self),
                };
                let trigger = nodes
                    .next()
                    .map(|n| trigger_build.node(n, window, cx))
                    .unwrap_or_else(|| div().into_any_element());
                // Its paths were numbered under `.content` when the tree was parsed.
                let content = self.subtree(Rc::new(nodes.cloned().collect()));
                let width = p["w"].as_f64().unwrap_or(280.) as f32;
                let surface = move |window: &mut Window, cx: &mut App| {
                    div().w(px(width)).p(px(12.)).child(content(window, cx))
                };
                if node.kind == "hover_card" {
                    HoverCard::new(id)
                        .trigger(trigger)
                        .content(move |_, window, cx| surface(window, cx))
                        .into_any_element()
                } else {
                    // A popover opens from a control: the trigger is a
                    // borderless button around the script's content.
                    let trigger = gpui_kit::component::button::Button::new(ElementId::Name(
                        format!("{key}-trigger").into(),
                    ))
                    .ghost()
                    .h_auto()
                    .p(px(0.))
                    .child(trigger);
                    let mut popover = Popover::new(id)
                        .trigger(trigger)
                        .content(move |_, window, cx| surface(window, cx));
                    if let Some(open) = p["open"].as_bool() {
                        popover = popover.open(open);
                    }
                    if let Some(h) = handler(p, "onOpenChange") {
                        let weak = self.weak.clone();
                        popover = popover.on_open_change(move |open, _, cx| {
                            let _ =
                                weak.update(cx, |view, cx| view.invoke(h, json!(*open), false, cx));
                        });
                    }
                    popover.into_any_element()
                }
            }
            "radio_group" => {
                let items = options(p);
                let selected = items.iter().position(|(v, _)| *v == p["value"]);
                let mut group = if p["horizontal"] == true {
                    RadioGroup::horizontal(id)
                } else {
                    RadioGroup::vertical(id)
                };
                group = group.selected_index(selected).disabled(disabled);
                for (i, (_, label)) in items.iter().enumerate() {
                    group = group.child(Radio::new(i).label(label.clone()));
                }
                let (build, change) = (self.clone(), handler(p, "onChange"));
                let values: Vec<Value> = items.into_iter().map(|(v, _)| v).collect();
                group
                    .on_change(move |index, _, cx| {
                        if let Some(value) = values.get(*index) {
                            build.call(change, value.clone(), cx);
                        }
                    })
                    .into_any_element()
            }
            "rating" => {
                let (build, change) = (self.clone(), handler(p, "onChange"));
                Rating::new(id)
                    .value(p["value"].as_u64().unwrap_or(0) as usize)
                    .max(p["max"].as_u64().unwrap_or(5).clamp(1, 10) as usize)
                    .disabled(disabled || change.is_none())
                    .on_click(move |value, _, cx| build.call(change, json!(*value), cx))
                    .into_any_element()
            }
            "kbd" => {
                let keys = text(p, "keys");
                match Keystroke::parse_with_os(&keys, OperatingSystem::Mac).ok() {
                    Some(stroke) => Kbd::new(stroke).into_any_element(),
                    None => ui::error("Kbd needs a shortcut such as \"cmd-k\"").into_any_element(),
                }
            }
            "tag" => {
                let tag = match p["variant"].as_str() {
                    Some("primary") => Tag::primary(),
                    Some("danger") => Tag::danger(),
                    Some("success") => Tag::success(),
                    Some("warning") => Tag::warning(),
                    Some("info") => Tag::info(),
                    _ => Tag::secondary(),
                };
                let tag = if p["outline"] == true {
                    tag.outline()
                } else {
                    tag
                };
                style(tag, node).child(text(p, "text")).into_any_element()
            }
            "skeleton" => style(Skeleton::new(), node).into_any_element(),
            "spinner" => {
                let mut spinner = Spinner::new();
                if let Some(c) = color(&p["color"]) {
                    spinner = spinner.color(c);
                }
                match p["size"].as_str() {
                    Some("small") => spinner.small().into_any_element(),
                    Some("large") => spinner.large().into_any_element(),
                    _ => spinner.into_any_element(),
                }
            }
            "description_list" => {
                let mut list = if p["vertical"] == true {
                    DescriptionList::vertical()
                } else {
                    DescriptionList::horizontal()
                };
                list = list
                    .columns(p["columns"].as_u64().unwrap_or(1).clamp(1, 4) as usize)
                    .bordered(p["bordered"] == true);
                for item in p["items"].as_array().into_iter().flatten() {
                    list = list.item(
                        SharedString::from(text(item, "label")),
                        SharedString::from(text(item, "value")),
                        item["span"].as_u64().unwrap_or(1).max(1) as usize,
                    );
                }
                list.into_any_element()
            }
            "pagination" => {
                let (build, change) = (self.clone(), handler(p, "onChange"));
                let mut pages = Pagination::new(id)
                    .total_pages(p["pages"].as_u64().unwrap_or(1).max(1) as usize)
                    .current_page(p["page"].as_u64().unwrap_or(1).max(1) as usize)
                    .on_click(move |page, _, cx| build.call(change, json!(*page), cx));
                if p["compact"] == true {
                    pages = pages.compact();
                }
                pages.into_any_element()
            }
            "accordion" => {
                let mut accordion = Accordion::new(id)
                    .multiple(p["multiple"] == true)
                    .bordered(p["bordered"] != false)
                    .disabled(disabled);
                let items = p["items"].as_array().cloned().unwrap_or_default();
                for (i, item) in items.iter().enumerate() {
                    let open = item["open"] == true;
                    // Closed sections build nothing.
                    let body = (open)
                        .then(|| children.get(i))
                        .flatten()
                        .map(|n| self.node(n, window, cx));
                    let title = text(item, "title");
                    accordion = accordion.item(move |it| {
                        let it = it.title(title).open(open);
                        match body {
                            Some(body) => it.child(body),
                            None => it,
                        }
                    });
                }
                let (build, toggle) = (self.clone(), handler(p, "onToggle"));
                accordion
                    .on_toggle_click(move |open, _, cx| build.call(toggle, json!(open), cx))
                    .into_any_element()
            }
            "breadcrumb" => {
                let select = handler(p, "onSelect");
                let items = options(p);
                let last = items.len().saturating_sub(1);
                let mut crumbs = Breadcrumb::new();
                for (i, (_, label)) in items.into_iter().enumerate() {
                    let mut item = BreadcrumbItem::new(label);
                    if i < last && select.is_some() {
                        let build = self.clone();
                        item = item.on_click(move |_, _, cx| build.call(select, json!(i), cx));
                    }
                    crumbs = crumbs.child(item);
                }
                crumbs.into_any_element()
            }
            "slider" => self.slider(node, &key, disabled, window, cx),
            "chart" => chart(node, id),
            "model_selector" => {
                let change = handler(p, "onChange");
                let build = self.clone();
                let on_change: super::OnChange =
                    Rc::new(move |value, cx| build.call(change, value, cx));
                let host = self.shared.host.borrow().clone();
                let mut props = p.clone();
                if disabled || change.is_none() {
                    props["disabled"] = json!(true);
                }
                if let Some(host) = host
                    && let Some(element) = host(
                        super::HostElement {
                            kind: "model_selector",
                            key: &key,
                            props: &props,
                            on_change,
                        },
                        window,
                        cx,
                    )
                {
                    return element;
                }
                // No window to draw the real selector (a screenshot): the same
                // trigger, showing the choice, without its sheet.
                let selection = &p["selection"];
                let shown = selection["model"]
                    .as_str()
                    .or(selection["profile"].as_str())
                    .map(|s| s.rsplit('/').next().unwrap_or(s).to_owned())
                    .unwrap_or_else(|| "Choose agent".into());
                ui::row()
                    .h(px(28.))
                    .px(px(6.))
                    .gap(px(6.))
                    .flex_none()
                    .child(Icon::new(IconName::Bot).size(px(14.)))
                    .child(div().text_size(px(ui::BODY)).child(shown))
                    .into_any_element()
            }
            "scene" => self.scene(node, window, cx),
            "image" => self.image(node, window, cx),
            // Rendered Markdown. Images never load: a view may not read files
            // or reach the network except through the broker. Links open
            // through the same check as host.openUrl.
            "markdown" => {
                let source = text(p, "text");
                let view = gpui_kit::component::text::TextView::markdown(id, source)
                    .selectable(self.selects(p))
                    .image_source(|_| {
                        ImageSource::Image(std::sync::Arc::new(Image::from_bytes(
                            ImageFormat::Png,
                            Vec::new(),
                        )))
                    })
                    .on_link_click(|url, _, _, cx| {
                        if crate::links::web_url(url).is_ok() {
                            cx.open_url(url);
                        }
                    });
                style(div().w_full().min_w_0(), node)
                    .child(view)
                    .into_any_element()
            }
            "avatar" => {
                let avatar = Avatar::new().name(text(p, "name"));
                match p["size"].as_str() {
                    Some("small") => avatar.small().into_any_element(),
                    Some("large") => avatar.large().into_any_element(),
                    _ => avatar.into_any_element(),
                }
            }
            other => ui::error(format!("Unknown element {other}")).into_any_element(),
        }
    }

    /// A native slider. The script owns the value: it moves the thumb only
    /// when the script's `value` changes, and hears `onChange` while the
    /// person drags and `onCommit` when they let go.
    fn slider(
        &self,
        node: &Node,
        key: &str,
        disabled: bool,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        let p = &node.p;
        let (min, max) = (
            p["min"].as_f64().unwrap_or(0.) as f32,
            p["max"].as_f64().unwrap_or(100.) as f32,
        );
        let step = p["step"].as_f64().unwrap_or(1.) as f32;
        let value = (p["value"].as_f64().unwrap_or(min as f64) as f32).clamp(min, max);
        self.register_late(key, p);
        let (shared, weak, slot_key) = (self.shared.clone(), self.weak.clone(), key.to_owned());
        let slot = window.use_keyed_state(
            ElementId::Name(format!("{}:{key}:slider", self.scope).into()),
            cx,
            move |_, cx| {
                let state = cx.new(|_| {
                    SliderState::new()
                        .min(min)
                        .max(max)
                        .step(step)
                        .default_value(value)
                });
                let events = cx.subscribe(&state, move |_, _, event: &SliderEvent, cx| {
                    // Changes stream while the thumb is dragged; only the
                    // release is a discrete gesture.
                    let (name, value, gesture) = match event {
                        SliderEvent::Change(v) => ("onChange", v, false),
                        SliderEvent::Release(v) => ("onCommit", v, true),
                    };
                    let v = match value {
                        SliderValue::Single(v) | SliderValue::Range(_, v) => v,
                    };
                    if let Some(h) = shared.late(&slot_key, name) {
                        let _ = weak.update(cx, |view, cx| view.invoke(h, json!(v), gesture, cx));
                    }
                });
                SliderSlot {
                    state,
                    applied: Cell::new(value),
                    _events: events,
                }
            },
        );
        let (state, applied) = {
            let slot = slot.read(cx);
            (slot.state.clone(), slot.applied.get())
        };
        if (applied - value).abs() > f32::EPSILON {
            slot.read(cx).applied.set(value);
            state.update(cx, |s, cx| s.set_value(value, window, cx));
        }
        let mut slider = Slider::new(&state).disabled(disabled);
        if let Some(label) = p["label"].as_str() {
            slider = slider.accessibility_label(label.to_owned());
        }
        style(div().w_full(), node).child(slider).into_any_element()
    }
}

/// One series as (label, value) points: `{ label, value }` objects or bare
/// numbers, which are labelled by position.
fn chart_points(p: &Value) -> Vec<(SharedString, f64)> {
    p["data"]
        .as_array()
        .into_iter()
        .flatten()
        .take(5_000)
        .enumerate()
        .filter_map(|(i, point)| match point {
            Value::Number(n) => Some(((i + 1).to_string().into(), n.as_f64()?)),
            Value::Object(_) => Some((
                text(point, "label").into(),
                point["value"].as_f64().filter(|v| v.is_finite())?,
            )),
            _ => None,
        })
        .collect()
}

/// A value as the chart's axis and tooltip show it.
fn chart_format(format: &str, prefix: &str, suffix: &str, signed: bool, value: f64) -> String {
    let body = match format {
        "percent" => format!("{}%", trim_number(value * 100., 1)),
        "compact" => {
            let (scaled, unit) = match value.abs() {
                v if v >= 1e9 => (value / 1e9, "B"),
                v if v >= 1e6 => (value / 1e6, "M"),
                v if v >= 1e3 => (value / 1e3, "k"),
                _ => (value, ""),
            };
            format!("{}{unit}", trim_number(scaled, 1))
        }
        _ => grouped(value),
    };
    // The sign leads the prefix: -$12, not $-12.
    match body.strip_prefix('-') {
        Some(rest) => format!("-{prefix}{rest}{suffix}"),
        None if signed && value > 0. => format!("+{prefix}{body}{suffix}"),
        None => format!("{prefix}{body}{suffix}"),
    }
}

/// At most `places` decimals, without trailing zeros.
fn trim_number(value: f64, places: usize) -> String {
    let text = format!("{value:.places$}");
    if text.contains('.') {
        text.trim_end_matches('0').trim_end_matches('.').to_owned()
    } else {
        text
    }
}

/// Thousands separated, up to two decimals.
fn grouped(value: f64) -> String {
    let text = trim_number(value, 2);
    let (sign, text) = text
        .strip_prefix('-')
        .map_or(("", text.as_str()), |t| ("-", t));
    let (whole, fraction) = text
        .split_once('.')
        .map_or((text, None), |(w, f)| (w, Some(f)));
    let mut out = String::new();
    for (i, digit) in whole.chars().enumerate() {
        if i > 0 && (whole.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(digit);
    }
    match fraction {
        Some(f) => format!("{sign}{out}.{f}"),
        None => format!("{sign}{out}"),
    }
}

/// A value axis on round numbers: (low, high, tick count). It always takes
/// in zero for bars and areas, and for lines whose values sit near it, so
/// heights compare honestly.
fn nice_domain(values: impl Iterator<Item = f64>, zero: bool) -> (f64, f64, usize) {
    let (mut lo, mut hi) = values.fold((f64::MAX, f64::MIN), |(lo, hi), v| (lo.min(v), hi.max(v)));
    if zero || lo > 0. && lo < hi * 0.5 || hi < 0. && hi > lo * 0.5 {
        lo = lo.min(0.);
        hi = hi.max(0.);
    }
    if hi < lo + f64::EPSILON {
        let pad = if hi == 0. { 1. } else { hi.abs() * 0.5 };
        lo -= pad;
        hi += pad;
        if zero || lo < 0. && hi > 0. {
            lo = lo.min(0.).max(if hi > 0. { 0. } else { lo });
        }
    }
    let rough = (hi - lo) / 5.;
    let magnitude = 10f64.powf(rough.log10().floor());
    let step = [1., 2., 2.5, 5., 10.]
        .into_iter()
        .map(|m| m * magnitude)
        .find(|step| *step >= rough)
        .unwrap_or(10. * magnitude);
    let low = (lo / step).floor() * step;
    let high = (hi / step).ceil() * step;
    let count = ((high - low) / step).round() as usize + 1;
    (low, high, count.clamp(2, 8))
}

/// A line, area or bar chart drawn by the host: axes, gridlines, a zero line
/// when values go negative, and a tooltip that snaps to the nearest point.
/// It fills its box; nothing runs in JavaScript while the pointer moves.
fn chart(node: &Rc<Node>, id: ElementId) -> AnyElement {
    use gpui_kit::component::chart::{AreaChart, BarChart, LineChart};
    let p = &node.p;
    let points = chart_points(p);
    let height = p["h"].as_f64().unwrap_or(200.).clamp(60., 2_000.) as f32;
    let frame = style(div().w_full().h(px(height)).min_w_0(), node);
    if points.is_empty() {
        return frame
            .flex()
            .items_center()
            .justify_center()
            .child(
                div()
                    .text_size(px(ui::SMALL))
                    .text_color(rgb(crate::sdk::ui::theme::get(2)))
                    .child(match p["empty"].as_str() {
                        Some(empty) => empty.to_owned(),
                        None => "No data yet".to_owned(),
                    }),
            )
            .into_any_element();
    }
    let accent = color(&p["color"]).unwrap_or(rgb(ui::theme::get(10)).into());
    let format = p["format"].as_str().unwrap_or("number").to_owned();
    let prefix = text(p, "prefix");
    let suffix = text(p, "suffix");
    let signed = p["signed"] == true;
    let show = {
        let (format, prefix, suffix) = (format.clone(), prefix.clone(), suffix.clone());
        Rc::new(move |v: f64| chart_format(&format, &prefix, &suffix, signed, v))
    };
    let negative = points.iter().any(|(_, v)| *v < 0.);
    let grid = p["grid"] != false;
    // About six labels along the bottom, whatever the length.
    let stride = points.len().div_ceil(6).max(1);
    let name: SharedString = text(p, "label").into();
    let tooltip = {
        let show = show.clone();
        move |_: &(SharedString, f64), v: f64| -> SharedString { show(v).into() }
    };
    let chart = match p["type"].as_str().unwrap_or("line") {
        "bar" => {
            let highlight = p["highlight"].as_u64().map(|i| i as usize);
            let muted = accent.opacity(0.35);
            let indexed: Vec<(usize, SharedString, f64)> = points
                .into_iter()
                .enumerate()
                .map(|(i, (l, v))| (i, l, v))
                .collect();
            // Bars grow both ways from their own zero baseline. Categories
            // compare by their values, so each bar carries its own label
            // and the axis between them goes.
            let show_label = show.clone();
            BarChart::new(indexed)
                .id(id)
                .appear(false)
                .name(name)
                .band(|d: &(usize, SharedString, f64)| d.1.clone())
                .value(|d| d.2)
                .tick_margin(stride)
                .grid(false)
                .value_axis(false)
                .label(move |d: &(usize, SharedString, f64)| show_label(d.2))
                .tooltip_value({
                    let show = show.clone();
                    move |_, v| show(v).into()
                })
                .fill(
                    move |d: &(usize, SharedString, f64), _, _, _| match highlight {
                        Some(i) if i != d.0 => muted,
                        _ => accent,
                    },
                )
                .into_any_element()
        }
        "area" => {
            let show_axis = show.clone();
            let (lo, hi, ticks) = nice_domain(points.iter().map(|p| p.1), true);
            let mut area = AreaChart::new(points)
                .id(id)
                .appear(false)
                .y_domain(lo, hi)
                .y_padding(0., 0.)
                .y_tick_count(ticks)
                .x(|d: &(SharedString, f64)| d.0.clone())
                .y(|d| d.1)
                .stroke(accent)
                .fill(accent.opacity(0.14))
                .linear()
                .name(name)
                .tick_margin(stride)
                .grid(grid)
                .y_axis(true)
                .y_tick_format(move |v| show_axis(v))
                .tooltip_value({
                    let show = show.clone();
                    move |_, _, v| show(v).into()
                });
            if negative {
                area = area.reference_line(0.);
            }
            area.into_any_element()
        }
        _ => {
            let show_axis = show.clone();
            let (lo, hi, ticks) = nice_domain(points.iter().map(|p| p.1), false);
            let mut line = LineChart::new(points)
                .id(id)
                .appear(false)
                .y_domain(lo, hi)
                .y_padding(0., 0.)
                .y_tick_count(ticks)
                .x(|d: &(SharedString, f64)| d.0.clone())
                .y(|d| d.1)
                .stroke(accent)
                .linear()
                .name(name)
                .tick_margin(stride)
                .grid(grid)
                .y_axis(true)
                .y_tick_format(move |v| show_axis(v))
                .tooltip_value(tooltip);
            if p["dots"] == true {
                line = line.dot();
            }
            if negative {
                line = line.reference_line(0.);
            }
            line.into_any_element()
        }
    };
    frame.child(chart).into_any_element()
}

impl Build {
    pub(super) fn workflow_outline(
        &self,
        node: &Rc<Node>,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        self.register_late(&node.key, &node.p);
        let editable = !self.read_only && handler(&node.p, "onEdit").is_some();
        let slot = window.use_keyed_state(
            ElementId::Name(format!("{}:{}:outline:{editable}", self.scope, node.key).into()),
            cx,
            |_, cx| {
                let outline = cx.new(|cx| {
                    let outline = meep_workflow_ui::Outline::new(
                        node.p["definition"].clone(),
                        node.p["trace"].clone(),
                        cx,
                    )
                    .with_source_icon(|name, _, size| {
                        crate::brands::logo(name, size).into_any_element()
                    });
                    if !editable {
                        return outline;
                    }
                    let (weak, shared, key) =
                        (self.weak.clone(), self.shared.clone(), node.key.clone());
                    outline.on_edit(Rc::new(move |target, _, cx| {
                        if let Some(callback) = shared.late(&key, "onEdit") {
                            let step = match target {
                                meep_workflow_ui::EditTarget::Script => Value::Null,
                                meep_workflow_ui::EditTarget::Step(step) => json!(step),
                            };
                            let _ =
                                weak.update(cx, |view, cx| view.invoke(callback, step, true, cx));
                        }
                    }))
                });
                (node.clone(), outline)
            },
        );
        let (last, outline) = slot.read(cx);
        let outline = outline.clone();
        if !Rc::ptr_eq(last, node) {
            if last.p["definition"] != node.p["definition"] || last.p["trace"] != node.p["trace"] {
                outline.update(cx, |outline, cx| {
                    outline.receive(node.p["definition"].clone(), node.p["trace"].clone(), cx)
                });
            }
            slot.update(cx, |state, _| state.0 = node.clone());
        }
        style(div().w_full().h(px(220.)).min_w_0().child(outline), node).into_any_element()
    }
}

#[cfg(test)]
mod chart_tests {
    use super::chart_format;

    #[test]
    fn values_read_the_way_people_write_them() {
        assert_eq!(
            chart_format("number", "", "", false, 12_345.678),
            "12,345.68"
        );
        assert_eq!(chart_format("number", "$", "", false, -1_200.), "-$1,200");
        assert_eq!(chart_format("percent", "", "", false, 0.125), "12.5%");
        assert_eq!(chart_format("percent", "", "", true, 0.04), "+4%");
        assert_eq!(chart_format("percent", "", "", true, -0.04), "-4%");
        assert_eq!(chart_format("percent", "", "", true, 0.), "0%");
        assert_eq!(chart_format("compact", "", "", false, 1_530_000.), "1.5M");
        assert_eq!(chart_format("compact", "", " ms", false, 980.), "980 ms");
    }

    #[test]
    fn axes_land_on_round_numbers() {
        use super::nice_domain;
        assert_eq!(
            nice_domain([444., 2331.].into_iter(), false),
            (0., 2500., 6)
        );
        let (lo, hi, n) = nice_domain([-0.018, 0., 0.071].into_iter(), true);
        assert!(
            (lo + 0.02).abs() < 1e-9 && (hi - 0.08).abs() < 1e-9 && n == 6,
            "{lo} {hi} {n}"
        );
        assert_eq!(nice_domain([90., 110.].into_iter(), false), (90., 110., 5));
        assert_eq!(nice_domain([5., 5.].into_iter(), true), (0., 5., 6));
    }
}
