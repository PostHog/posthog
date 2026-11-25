use super::*;
/// Lifts the sheet off the composer it opens over: a contact edge, a close
/// shadow for shape and a wide one for height.
fn sheet_shadow(progress: f32) -> Vec<BoxShadow> {
    // GPUI fades each primitive on its own, so a fading sheet would show its
    // shadow through itself. The shadow arrives last.
    let ink = progress.clamp(0., 1.).powi(3);
    let shadows = vec![
        BoxShadow {
            color: rgba(0x0000001a).into(),
            offset: point(px(0.), px(0.)),
            blur_radius: px(0.),
            spread_radius: px(0.5),
            inset: false,
        },
        BoxShadow {
            color: rgba(0x0000000f).into(),
            offset: point(px(0.), px(2.)),
            blur_radius: px(6.),
            spread_radius: px(0.),
            inset: false,
        },
        BoxShadow {
            color: rgba(0x0000001c).into(),
            offset: point(px(0.), px(12.)),
            blur_radius: px(32.),
            spread_radius: px(-4.),
            inset: false,
        },
    ];
    shadows
        .into_iter()
        .map(|mut shadow| {
            shadow.color = shadow.color.opacity(ink);
            shadow
        })
        .collect()
}

/// What the sheet's motion remembers between frames: its measured content
/// height, and counters that give each opening and each page turn a fresh
/// animation.
#[derive(Default)]
pub(super) struct PickerMotion {
    height: std::cell::Cell<f32>,
    opens: std::cell::Cell<u32>,
    turns: std::cell::Cell<u32>,
}

impl PickerMotion {
    pub(super) fn opened(&self) {
        self.opens.set(self.opens.get().wrapping_add(1));
        self.turns.set(0);
        self.height.set(0.);
    }
    pub(super) fn turned(&self) {
        self.turns.set(self.turns.get().wrapping_add(1));
    }
}

pub(super) fn finish(
    sheet: Stateful<Div>,
    page: Div,
    motion: std::rc::Rc<PickerMotion>,
    agents: bool,
    window: &mut Window,
    cx: &mut App,
) -> AnyElement {
    let opens = motion.opens.get();
    let turns = motion.turns.get();
    let page = if turns == 0 {
        page.into_any_element()
    } else {
        let from = if agents { -8. } else { 8. };
        page.relative()
            .with_animation(
                SharedString::from(format!("agent-picker-page-{opens}-{turns}")),
                Animation::new(ui::motion::NORMAL)
                    .with_easing(|t| ui::motion::ease_out().sample(t)),
                move |page, delta| {
                    page.left(px(ui::motion::travel(delta, from)))
                        .opacity(delta)
                },
            )
            .into_any_element()
    };
    // Measure the content's natural height every frame; the clip follows it.
    let probe = {
        let motion = motion.clone();
        canvas(
            move |bounds, window, _| {
                let height = f32::from(bounds.size.height);
                if (height - motion.height.get()).abs() > 0.5 {
                    motion.height.set(height);
                    window.refresh();
                }
            },
            |_, _, _, _| {},
        )
        .absolute()
        .inset_0()
    };
    let content = div().relative().w_full().child(page).child(probe);
    let measured = motion.height.get();
    let body = if measured <= 0. {
        // First frame of an opening: lay out naturally to learn the height.
        content.into_any_element()
    } else {
        let height = gpui_kit::base::spring(
            ElementId::from(SharedString::from(format!("agent-picker-height-{opens}"))),
            measured,
            cx.theme().motion_tokens().spring_control,
            window,
            cx,
        );
        div()
            .relative()
            .w_full()
            .h(px(height))
            .overflow_hidden()
            .child(content.absolute().left_0().bottom_0().w_full())
            .into_any_element()
    };
    sheet
        .child(body)
        .with_animation(
            SharedString::from(format!("agent-picker-enter-{opens}")),
            Animation::new(ui::motion::NORMAL).with_easing(|t| ui::motion::ease_out().sample(t)),
            move |sheet, delta| {
                sheet
                    .top(px(ui::motion::travel(delta, 6.)))
                    .opacity(delta)
                    .shadow(sheet_shadow(delta))
            },
        )
        .into_any_element()
}
