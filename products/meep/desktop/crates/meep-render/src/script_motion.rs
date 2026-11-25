//! Declarative motion for script views: gpui-kit's motion SDK behind one
//! `motion` prop. The script states values (initial, animate, exit, keyframes)
//! and a timing; the host samples them natively every frame, so no JavaScript
//! runs while anything moves. Reduced Motion and keyboard use settle instantly
//! through the same policy as the rest of the app.
use crate::sdk::ui;
use gpui_kit::base::{
    Easing, Interpolate, IterationCount, Keyframe, Keyframes, LinearStop, PlaybackDirection,
    Presence, Spring, Stagger, StaggerOrigin, StepPosition, Timing, Transition,
};
use gpui_kit::*;
use serde_json::Value;
use std::time::Duration;

/// Animatable properties, in slot order. Colours take four slots (RGBA).
const KEYS: [&str; 8] = ["x", "y", "opacity", "w", "h", "radius", "scale", "rotate"];
const COLORS: [&str; 3] = ["bg", "color", "borderColor"];
const N: usize = KEYS.len() + COLORS.len() * 4;
const LONGEST: Duration = Duration::from_millis(2000);

#[derive(Clone, Copy, PartialEq)]
struct Values([f32; N]);
impl Interpolate for Values {
    fn interpolate(&self, target: &Self, t: f32) -> Self {
        let mut out = self.0;
        for (o, b) in out.iter_mut().zip(target.0) {
            *o += (b - *o) * t;
        }
        Values(out)
    }
}

/// One sampled frame: the values the element paints with, and which of them
/// the script animates. Untouched properties keep the element's own styling.
#[derive(Clone, Copy)]
pub struct Frame {
    values: [f32; N],
    mask: [bool; N],
}
impl Frame {
    /// `frame` moved by a further `dx`, `dy`: where a drag let go of it.
    pub fn moved(frame: Option<Frame>, dx: f32, dy: f32) -> Frame {
        let mut f = frame.unwrap_or(Frame {
            values: [0.; N],
            mask: [false; N],
        });
        for (i, d) in [(0, dx), (1, dy)] {
            if !f.mask[i] {
                f.values[i] = 0.;
            }
            f.values[i] += d;
            f.mask[i] = true;
        }
        f
    }
    fn get(&self, key: &str) -> Option<f32> {
        let i = KEYS.iter().position(|k| *k == key)?;
        self.mask[i].then_some(self.values[i])
    }
    fn color(&self, key: &str) -> Option<Hsla> {
        let i = KEYS.len() + COLORS.iter().position(|k| *k == key)? * 4;
        self.mask[i].then(|| {
            let v = &self.values[i..i + 4];
            Rgba {
                r: v[0],
                g: v[1],
                b: v[2],
                a: v[3],
            }
            .into()
        })
    }
    /// Applies the frame over an element's static style (`p`).
    pub fn apply<E: Styled>(&self, mut e: E, p: &Value) -> E {
        let (x, y) = (self.get("x"), self.get("y"));
        if x.is_some() || y.is_some() {
            e = offset(e, p, x.unwrap_or(0.), y.unwrap_or(0.));
        }
        if let Some(o) = self.get("opacity") {
            e = e.opacity(o.clamp(0., 1.));
        }
        if let Some(w) = self.get("w") {
            e = e.w(px(w.max(0.)));
        }
        if let Some(h) = self.get("h") {
            e = e.h(px(h.max(0.)));
        }
        if let Some(r) = self.get("radius") {
            e = e.rounded(px(r.max(0.)));
        }
        if let Some(c) = self.color("bg") {
            e = e.bg(c);
        }
        if let Some(c) = self.color("color") {
            e = e.text_color(c);
        }
        if let Some(c) = self.color("borderColor") {
            e = e.border_color(c);
        }
        e
    }
    /// Scale and rotation paint only on vector marks (icons): GPUI transforms
    /// SVGs, not layout boxes.
    pub fn transformation(&self) -> Option<Transformation> {
        let scale = self.get("scale");
        let rotate = self.get("rotate");
        if scale.is_none() && rotate.is_none() {
            return None;
        }
        let s = scale.unwrap_or(1.).max(0.);
        Some(
            Transformation::scale(size(s, s))
                .with_rotation(radians(rotate.unwrap_or(0.).to_radians())),
        )
    }
}

/// Moves an element by (dx, dy) without changing how it is laid out. An
/// element in normal flow shifts relatively; an absolutely positioned one
/// moves through its own anchors, so it never drops out of its layer (making
/// it `relative` mid-animation would pull it into the flow and then snap).
pub fn offset<E: Styled>(mut e: E, p: &Value, dx: f32, dy: f32) -> E {
    if p["position"] != "absolute" {
        return e.relative().left(px(dx)).top(px(dy));
    }
    let anchor = |key: &str| {
        p[key]
            .as_f64()
            .or_else(|| p["inset"].as_f64())
            .map(|v| v as f32)
    };
    if dy != 0. {
        e = match (anchor("top"), anchor("bottom")) {
            (Some(t), b) => {
                let e = e.top(px(t + dy));
                if let Some(b) = b {
                    e.bottom(px(b - dy))
                } else {
                    e
                }
            }
            (None, Some(b)) => e.bottom(px(b - dy)),
            (None, None) => e.top(px(dy)),
        };
    }
    if dx != 0. {
        e = match (anchor("left"), anchor("right")) {
            (Some(l), r) => {
                let e = e.left(px(l + dx));
                if let Some(r) = r {
                    e.right(px(r - dx))
                } else {
                    e
                }
            }
            (None, Some(r)) => e.right(px(r - dx)),
            (None, None) => e.left(px(dx)),
        };
    }
    e
}

/// Reads a props object ({ x, opacity, bg, ... }) over `base`, marking what it sets.
fn read(
    props: &Value,
    base: &mut [f32; N],
    mask: &mut [bool; N],
    color: &dyn Fn(&Value) -> Option<Hsla>,
) {
    let Some(props) = props.as_object() else {
        return;
    };
    for (i, key) in KEYS.iter().enumerate() {
        if let Some(v) = props.get(*key).and_then(Value::as_f64) {
            base[i] = v as f32;
            mask[i] = true;
        }
    }
    for (c, key) in COLORS.iter().enumerate() {
        if let Some(rgba) = props.get(*key).and_then(color).map(Rgba::from) {
            let i = KEYS.len() + c * 4;
            base[i..i + 4].copy_from_slice(&[rgba.r, rgba.g, rgba.b, rgba.a]);
            mask[i] = true;
        }
    }
}

/// The element's resting value for each property, from its own style props,
/// so `animate: { x: 40 }` starts from where the element already is.
fn rest(p: &Value, color: &dyn Fn(&Value) -> Option<Hsla>) -> [f32; N] {
    let mut v = [0.; N];
    v[2] = p["opacity"].as_f64().unwrap_or(1.) as f32;
    v[3] = p["w"].as_f64().unwrap_or(0.) as f32;
    v[4] = p["h"].as_f64().unwrap_or(0.) as f32;
    v[5] = p["radius"].as_f64().unwrap_or(0.) as f32;
    v[6] = 1.;
    for (c, key) in COLORS.iter().enumerate() {
        let i = KEYS.len() + c * 4;
        // A colour that animates from nothing starts transparent.
        let rgba = color(&p[*key]).map(Rgba::from).unwrap_or(Rgba {
            r: 0.,
            g: 0.,
            b: 0.,
            a: 0.,
        });
        v[i..i + 4].copy_from_slice(&[rgba.r, rgba.g, rgba.b, rgba.a]);
    }
    v
}

fn ms(value: &Value, default: Duration) -> Duration {
    value
        .as_f64()
        .map(|n| Duration::from_millis(n.clamp(0., LONGEST.as_millis() as f64) as u64))
        .unwrap_or(default)
}

/// `"out"`, `"in"`, `"in-out"`, `"move"`, `"linear"`, `"ease"`, a cubic
/// bezier `[x1, y1, x2, y2]`, `{ steps, position }` or `{ linear: [...] }`.
pub fn easing(value: &Value) -> Easing {
    match value {
        Value::String(name) => match name.as_str() {
            "linear" => Easing::Linear,
            "ease" => Easing::Ease,
            "in" => Easing::EaseIn,
            "in-out" => Easing::EaseInOut,
            "move" => ui::motion::ease_move(),
            _ => ui::motion::ease_out(),
        },
        Value::Array(points) if points.len() == 4 => {
            let n: Vec<f32> = points
                .iter()
                .map(|p| p.as_f64().unwrap_or(0.) as f32)
                .collect();
            Easing::cubic_bezier(n[0], n[1], n[2], n[3]).unwrap_or_else(|_| ui::motion::ease_out())
        }
        Value::Object(o) if o.contains_key("steps") => {
            let position = match o.get("position").and_then(Value::as_str) {
                Some("start") => StepPosition::JumpStart,
                Some("none") => StepPosition::JumpNone,
                Some("both") => StepPosition::JumpBoth,
                _ => StepPosition::JumpEnd,
            };
            let count = o["steps"].as_u64().unwrap_or(1).clamp(1, 100) as u32;
            Easing::steps(count, position).unwrap_or(Easing::Linear)
        }
        Value::Object(o) if o.contains_key("linear") => {
            let stops = o["linear"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|s| match s {
                    Value::Array(pair) => LinearStop::at(
                        pair.first().and_then(Value::as_f64).unwrap_or(0.) as f32,
                        pair.get(1).and_then(Value::as_f64).unwrap_or(0.) as f32,
                    ),
                    other => LinearStop::new(other.as_f64().unwrap_or(0.) as f32),
                });
            Easing::linear_stops(stops).unwrap_or(Easing::Linear)
        }
        _ => ui::motion::ease_out(),
    }
}

/// `stagger: { index, count, interval, from }`: the delay for item `index`.
fn stagger(value: &Value) -> Duration {
    let Some(o) = value.as_object() else {
        return Duration::ZERO;
    };
    let index = o.get("index").and_then(Value::as_u64).unwrap_or(0) as usize;
    let count = o
        .get("count")
        .and_then(Value::as_u64)
        .map(|c| c as usize)
        .unwrap_or(index + 1);
    let origin = match o.get("from") {
        Some(Value::String(s)) if s == "last" => StaggerOrigin::Last,
        Some(Value::String(s)) if s == "center" => StaggerOrigin::Center,
        Some(Value::Number(n)) => StaggerOrigin::Index(n.as_u64().unwrap_or(0) as usize),
        _ => StaggerOrigin::First,
    };
    let interval = ms(
        o.get("interval").unwrap_or(&Value::Null),
        Duration::from_millis(30),
    );
    Stagger::new(interval, origin)
        .delay(index, count)
        .min(LONGEST)
}

/// The curves sheets slide in and out on.
const SHEET_EASE: [f32; 4] = [0.32, 0.72, 0., 1.];
const SHEET_EXIT_EASE: [f32; 4] = [0.3, 0., 0.1, 1.];

/// The `enter`/`show`/`delay` shorthands, written as a full motion spec.
fn shorthand(p: &Value) -> Value {
    let (x, y) = match p["enter"].as_str().unwrap_or("fade") {
        "rise" => (0., 8.),
        "drop" => (0., -8.),
        "slide-left" => (16., 0.),
        "slide-right" => (-16., 0.),
        // A sheet rises from the edge it lives on: its full height, and its
        // shadow's, so nothing of it shows before it moves.
        "sheet" => (0., p["h"].as_f64().map_or(240., |h| h + 24.) as f32),
        _ => (0., 0.),
    };
    let sheet = p["enter"] == "sheet";
    // A sheet slides, it doesn't ghost: with a known height it travels all of
    // it fully opaque; otherwise it fades a little to hide where it starts.
    let opacity = match (sheet, p["h"].is_number()) {
        (true, true) => 1.,
        (true, false) => 0.6,
        _ => 0.,
    };
    let mut spec = serde_json::json!({
        "initial": { "opacity": opacity, "x": x, "y": y },
        "exit": { "opacity": opacity, "x": x, "y": y },
        "transition": {
            "delay": p["delay"].as_f64().unwrap_or(0.).min(300.),
            // Larger travel takes a little longer; exits stay quicker.
            "duration": if sheet { 280. } else { 180. },
            "exitDuration": if sheet { 240. } else { 120. },
        },
    });
    if sheet {
        // Long travel on View's curve jumps in its first frame. A sheet
        // decelerates in, and on the way out speeds up first, so the part
        // still on screen isn't spent in one frame.
        spec["transition"]["ease"] = serde_json::json!(SHEET_EASE);
        spec["transition"]["exitEase"] = serde_json::json!(SHEET_EXIT_EASE);
    }
    spec
}

/// An exit follows the declared curve (`exitEase`, else `ease`), so a scrim
/// and its sheet leave together. View's own curve front-loads a long exit
/// into its first frame.
fn exit_easing(timing: &Value) -> Easing {
    match &timing["exitEase"] {
        Value::Null => easing(&timing["ease"]),
        ease => easing(ease),
    }
}

/// Whether the element declares motion at all.
pub fn declared(p: &Value) -> bool {
    p.get("motion").is_some() || p.get("enter").is_some() || p.get("show").is_some()
}

pub enum Sampled {
    /// Fully exited: render nothing.
    Gone,
    /// Paint this frame (`None` when the element is at rest unchanged).
    Frame(Option<Frame>),
}

/// Samples the element's motion for this frame.
pub fn sample(
    scope: &str,
    key: &str,
    p: &Value,
    color: &dyn Fn(&Value) -> Option<Hsla>,
    window: &mut Window,
    cx: &mut App,
) -> Sampled {
    let short;
    let spec = match p.get("motion") {
        Some(m) if m.is_object() => m,
        _ => {
            short = shorthand(p);
            &short
        }
    };
    let id = |part: &str| ElementId::Name(format!("{scope}:{key}:{part}").into());
    let timing = &spec["transition"];
    let base = rest(p, color);
    let mut mask = [false; N];
    let mut target = base;
    read(&spec["animate"], &mut target, &mut mask, color);
    let delay = ms(&timing["delay"], Duration::ZERO) + stagger(&spec["stagger"]);
    let duration = ms(&timing["duration"], ui::motion::NORMAL);

    // Keyframes and repeats play from mount (or when the element's `id` changes).
    let mut current = if let Some(frames) = spec["keyframes"].as_array().filter(|f| f.len() >= 2) {
        let last = frames.len() - 1;
        let built: Vec<Keyframe<Values>> = frames
            .iter()
            .enumerate()
            .map(|(i, frame)| {
                let mut v = target;
                read(frame, &mut v, &mut mask, color);
                let offset = frame["offset"]
                    .as_f64()
                    .map(|o| o as f32)
                    .unwrap_or(i as f32 / last as f32);
                let mut k = Keyframe::new(offset.clamp(0., 1.), Values(v));
                if !frame["ease"].is_null() {
                    k = k.ease(easing(&frame["ease"]));
                }
                k
            })
            .collect();
        match Keyframes::try_new(built) {
            Ok(keyframes) => {
                let iterations = match &timing["repeat"] {
                    Value::String(s) if s == "infinite" => IterationCount::Infinite,
                    Value::Number(n) => {
                        IterationCount::Finite(n.as_u64().unwrap_or(0).min(1000) + 1)
                    }
                    _ => IterationCount::Finite(1),
                };
                let direction = match timing["direction"].as_str() {
                    Some("reverse") => PlaybackDirection::Reverse,
                    Some("alternate") => PlaybackDirection::Alternate,
                    Some("alternate-reverse") => PlaybackDirection::AlternateReverse,
                    _ => PlaybackDirection::Normal,
                };
                let t = Timing::new(duration)
                    .delay(delay.into())
                    .iterations(iterations)
                    .direction(direction)
                    .ease(easing(&timing["ease"]));
                gpui_kit::base::animate_keyframes(id("keyframes"), &keyframes, t, window, cx)
                    .value
                    .0
            }
            Err(_) => target,
        }
    } else if timing["type"] == "spring" {
        // A spring keeps its velocity when the target changes mid-flight.
        let response = ms(&timing["response"], ui::motion::NORMAL).max(Duration::from_millis(50));
        let damping = timing["damping"].as_f64().unwrap_or(1.).clamp(0.1, 2.) as f32;
        let policy = Spring::new(response).with_damping(damping);
        let mut v = target;
        for (i, slot) in v.iter_mut().enumerate() {
            if mask[i] {
                *slot = gpui_kit::base::spring(id(&format!("s{i}")), *slot, policy, window, cx);
            }
        }
        v
    } else {
        let policy = Transition::new(duration)
            .delay(delay)
            .easing(easing(&timing["ease"]));
        gpui_kit::base::transition(id("tween"), Values(target), policy, window, cx).0
    };

    // Presence: initial on mount, exit when `show` turns false.
    let has_initial = spec["initial"].is_object();
    let has_exit = spec["exit"].is_object();
    if has_initial || has_exit || p.get("show").is_some() {
        let present = p["show"] != false;
        let (mut from, mut from_mask) = (current, mask);
        let source = if present || !has_exit {
            &spec["initial"]
        } else {
            &spec["exit"]
        };
        read(source, &mut from, &mut from_mask, color);
        // Exits are quicker than entries and never wait.
        let presence = if present {
            Transition::new(duration)
                .delay(delay)
                .easing(easing(&timing["ease"]))
        } else {
            Transition::new(ms(&timing["exitDuration"], ui::motion::FAST))
                .easing(exit_easing(timing))
        };
        let sample = Presence::new(id("presence"), present)
            .transition(presence)
            .sample(window, cx);
        if !sample.should_render() {
            return Sampled::Gone;
        }
        let t = sample.progress.clamp(0., 1.);
        if t < 1. {
            current = Values(from).interpolate(&Values(current), t).0;
            mask = from_mask;
        }
    }
    if !mask.iter().any(|m| *m) {
        return Sampled::Frame(None);
    }
    Sampled::Frame(Some(Frame {
        values: current,
        mask,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[::core::prelude::v1::test]
    fn easings_parse_every_form() {
        for e in [
            serde_json::json!("out"),
            serde_json::json!("linear"),
            serde_json::json!([0.2, 0.0, 0.0, 1.0]),
            serde_json::json!({"steps": 4, "position": "start"}),
            serde_json::json!({"linear": [0, [0.5, 0.8], 1]}),
        ] {
            let curve = easing(&e);
            assert_eq!(curve.sample(1.), 1.);
        }
    }
    #[::core::prelude::v1::test]
    fn stagger_counts_from_its_origin_and_is_capped() {
        let d = |v| stagger(&v);
        assert_eq!(
            d(serde_json::json!({"index": 3})),
            Duration::from_millis(90)
        );
        assert_eq!(
            d(serde_json::json!({"index": 0, "count": 5, "from": "last"})),
            Duration::from_millis(120)
        );
        assert_eq!(
            d(serde_json::json!({"index": 999, "interval": 500})),
            LONGEST
        );
    }
    #[::core::prelude::v1::test]
    fn exits_follow_the_declared_curve() {
        let at = |timing: Value| exit_easing(&timing).sample(0.25);
        let view = ui::motion::ease_out().sample(0.25);
        assert_eq!(at(serde_json::json!({})), view);
        assert_eq!(at(serde_json::json!({"ease": "linear"})), 0.25);
        assert_eq!(
            at(serde_json::json!({"ease": "out", "exitEase": "linear"})),
            0.25
        );
    }
    #[::core::prelude::v1::test]
    fn a_sheet_slides_its_full_height_opaque() {
        let spec = shorthand(&serde_json::json!({"enter": "sheet", "h": 400}));
        assert_eq!(spec["initial"]["y"], 424.);
        assert_eq!(spec["initial"]["opacity"], 1.);
        assert!(spec["transition"]["exitEase"].is_array());
        // Without a known height it can't travel all of it, so it fades a little.
        let spec = shorthand(&serde_json::json!({"enter": "sheet", "h": "60%"}));
        assert!(spec["initial"]["opacity"].as_f64().unwrap() < 1.);
    }
}
