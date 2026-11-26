use super::*;
use std::{
    cell::{Cell, RefCell},
    collections::VecDeque,
    rc::Rc,
    time::{Duration, Instant},
};

const DELAY: Duration = Duration::from_millis(16);

struct Sample {
    event: ScrollEvent,
    start: Instant,
    end: Instant,
    sent: Point<Pixels>,
}

#[derive(Default)]
pub(super) struct ScrollMotion {
    samples: RefCell<VecDeque<Sample>>,
    scheduled: Cell<bool>,
    delivering: Cell<bool>,
}

impl ScrollMotion {
    pub(super) fn listener(self: &Rc<Self>) -> impl IntoElement {
        let motion = self.clone();
        canvas(
            |_, _, _| (),
            move |_, _, window, _| {
                let clear = motion.clone();
                window.on_mouse_event(move |_: &MouseDownEvent, phase, _, _| {
                    if phase == DispatchPhase::Capture {
                        clear.samples.borrow_mut().clear();
                    }
                });
                let clear = motion.clone();
                window.on_key_event(move |_: &KeyDownEvent, phase, _, _| {
                    if phase == DispatchPhase::Capture {
                        clear.samples.borrow_mut().clear();
                    }
                });
                let motion = motion.clone();
                window.on_mouse_event(move |event: &ScrollEvent, phase, window, cx| {
                    if phase != DispatchPhase::Capture || motion.delivering.get() {
                        return;
                    }
                    if !matches!(event.delta, ScrollDelta::Pixels(_))
                        || event.source != ScrollSource::Pointer
                        || event.modifiers != Modifiers::default()
                        || event.touch_phase == TouchPhase::Cancelled
                        || cx.reduce_motion()
                    {
                        motion.samples.borrow_mut().clear();
                        return;
                    }
                    if event.touch_phase == TouchPhase::Started
                        && motion.samples.borrow().is_empty()
                    {
                        return;
                    }
                    let now = Instant::now();
                    let end = now + DELAY;
                    let mut samples = motion.samples.borrow_mut();
                    let start = samples.back().map_or(now, |s| s.end.max(now));
                    samples.push_back(Sample {
                        event: event.clone(),
                        start,
                        end,
                        sent: Point::default(),
                    });
                    drop(samples);
                    cx.stop_propagation();
                    motion.schedule(window);
                });
            },
        )
        .absolute()
        .size_0()
    }

    fn schedule(self: &Rc<Self>, window: &mut Window) {
        if self.scheduled.replace(true) {
            return;
        }
        let weak = Rc::downgrade(self);
        window.on_next_frame(move |window, cx| {
            let Some(motion) = weak.upgrade() else { return };
            motion.scheduled.set(false);
            let now = Instant::now();
            motion.delivering.set(true);
            loop {
                let mut samples = motion.samples.borrow_mut();
                let Some(sample) = samples.front_mut() else {
                    break;
                };
                let done = now >= sample.end;
                if !done && (now <= sample.start || sample.event.touch_phase != TouchPhase::Moved) {
                    break;
                }
                let ScrollDelta::Pixels(total) = sample.event.delta else {
                    unreachable!()
                };
                let fraction = if done {
                    1.
                } else {
                    now.duration_since(sample.start).as_secs_f32()
                        / sample.end.duration_since(sample.start).as_secs_f32()
                };
                let offset = total.map(|axis| axis * fraction);
                let step = offset - sample.sent;
                sample.sent = offset;
                let mut event = sample.event.clone();
                event.delta = ScrollDelta::Pixels(step);
                if done {
                    samples.pop_front();
                }
                drop(samples);
                if step != Point::default() || event.touch_phase != TouchPhase::Moved {
                    window.dispatch_event(PlatformInput::Scroll(event), cx);
                }
                if !done {
                    break;
                }
            }
            motion.delivering.set(false);
            if !motion.samples.borrow().is_empty() {
                motion.schedule(window);
            }
        });
    }
}
