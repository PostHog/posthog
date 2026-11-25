//! A driver for recording demos (feature `demo-driver`). With `MEEP_DEMO_SOCKET` set,
//! the app reads input from that Unix socket and replays it into its own window, so a
//! screencast can run while the person keeps using the machine. One JSON object per line:
//! `{"op":"move","x":..,"y":..}`, `down`, `up`, `{"op":"scroll","x":..,"y":..,"dy":..}`,
//! `{"op":"text","text":".."}`, `{"op":"key","key":"cmd-enter"}`. Positions are window points.
use super::*;
use std::io::{BufRead, BufReader};
use std::os::unix::net::UnixListener;
use std::sync::{Mutex, mpsc};

/// Where the replayed pointer is, for the drawn cursor (the real one is elsewhere).
static POINTER: Mutex<Option<(f32, f32)>> = Mutex::new(None);

/// A classic arrow at the replayed pointer, drawn above everything, so a recording of
/// the window shows where the driver points and clicks.
pub(crate) fn cursor() -> Option<AnyElement> {
    let (x, y) = (*POINTER.lock().ok()?)?;
    let arrow = |scale: f32, dx: f32, dy: f32| {
        let at = |px_: f32, py_: f32| point(px(dx + px_ * scale), px(dy + py_ * scale));
        let mut b = PathBuilder::fill();
        b.move_to(at(0., 0.));
        b.line_to(at(0., 17.));
        b.line_to(at(4.2, 13.2));
        b.line_to(at(7.2, 19.8));
        b.line_to(at(10., 18.6));
        b.line_to(at(7.1, 12.2));
        b.line_to(at(12.6, 12.2));
        b.close();
        b
    };
    Some(
        deferred(
            div()
                .absolute()
                .left(px(x - 1.))
                .top(px(y - 1.))
                .size(px(24.))
                .child(canvas(
                    |_, _, _| (),
                    move |bounds, _, w, _| {
                        let o = bounds.origin;
                        let (ox, oy) = (f32::from(o.x), f32::from(o.y));
                        if let Ok(path) = arrow(1.18, ox, oy).build() {
                            w.paint_path(path, gpui_kit::black());
                        }
                        if let Ok(path) = arrow(0.86, ox + 1.35, oy + 2.6).build() {
                            w.paint_path(path, gpui_kit::white());
                        }
                    },
                )),
        )
        .with_priority(10_000)
        .into_any_element(),
    )
}

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "lowercase")]
enum Input {
    Move { x: f32, y: f32 },
    Down { x: f32, y: f32 },
    Up { x: f32, y: f32 },
    Scroll { x: f32, y: f32, dy: f32 },
    Text { text: String },
    Key { key: String },
}

pub(crate) fn start(window: AnyWindowHandle, cx: &mut App) {
    let Some(path) = std::env::var_os("MEEP_DEMO_SOCKET") else {
        return;
    };
    let (tx, rx) = mpsc::channel::<Input>();
    std::thread::spawn(move || {
        let _ = std::fs::remove_file(&path);
        let Ok(listener) = UnixListener::bind(&path) else {
            eprintln!("demo driver: cannot bind {}", path.to_string_lossy());
            return;
        };
        for stream in listener.incoming().flatten() {
            for line in BufReader::new(stream).lines().map_while(Result::ok) {
                match serde_json::from_str::<Input>(&line) {
                    Ok(input) => {
                        let _ = tx.send(input);
                    }
                    Err(e) => eprintln!("demo driver: {e}: {line}"),
                }
            }
        }
    });
    cx.spawn(async move |cx| {
        loop {
            cx.background_executor()
                .timer(std::time::Duration::from_millis(4))
                .await;
            while let Ok(input) = rx.try_recv() {
                let updated = window.update(cx, |_, w, cx| {
                    replay(input, w, cx);
                    w.refresh();
                });
                if std::env::var_os("MEEP_DEMO_LOG").is_some() {
                    eprintln!(
                        "demo driver: replayed ({})",
                        if updated.is_ok() { "ok" } else { "no window" }
                    );
                }
            }
        }
    })
    .detach();
}

fn replay(input: Input, w: &mut Window, cx: &mut App) {
    let at = |x: f32, y: f32| point(px(x), px(y));
    if let Input::Move { x, y } | Input::Down { x, y } | Input::Up { x, y } = &input
        && let Ok(mut pointer) = POINTER.lock()
    {
        *pointer = Some((*x, *y));
    }
    match input {
        Input::Move { x, y } => {
            w.dispatch_event(
                PlatformInput::MouseMove(MouseMoveEvent {
                    position: at(x, y),
                    pressed_button: None,
                    modifiers: Modifiers::default(),
                }),
                cx,
            );
        }
        Input::Down { x, y } => {
            w.dispatch_event(
                PlatformInput::MouseDown(MouseDownEvent {
                    button: MouseButton::Left,
                    position: at(x, y),
                    modifiers: Modifiers::default(),
                    click_count: 1,
                    first_mouse: false,
                }),
                cx,
            );
        }
        Input::Up { x, y } => {
            w.dispatch_event(
                PlatformInput::MouseUp(MouseUpEvent {
                    button: MouseButton::Left,
                    position: at(x, y),
                    modifiers: Modifiers::default(),
                    click_count: 1,
                }),
                cx,
            );
        }
        Input::Scroll { x, y, dy } => {
            w.dispatch_event(
                PlatformInput::Scroll(ScrollEvent {
                    position: at(x, y),
                    delta: ScrollDelta::Pixels(point(px(0.), px(dy))),
                    ..Default::default()
                }),
                cx,
            );
        }
        Input::Text { text } => {
            for c in text.chars() {
                let key = c.to_string();
                w.dispatch_keystroke(
                    Keystroke {
                        modifiers: Modifiers::default(),
                        key: key.clone(),
                        key_char: Some(key),
                    },
                    cx,
                );
            }
        }
        Input::Key { key } => {
            // Parsing wants a static name; the driver sends a handful of short ones.
            let parsed = Keystroke::parse(Box::leak(key.into_boxed_str())).ok();
            if let Some(keystroke) = parsed {
                w.dispatch_keystroke(keystroke, cx);
            }
        }
    }
}
