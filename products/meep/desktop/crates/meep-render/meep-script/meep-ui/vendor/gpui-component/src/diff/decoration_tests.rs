use std::{cell::RefCell, rc::Rc};

use gpui::{
    AppContext as _, Context, Entity, InteractiveElement as _, IntoElement, ParentElement as _,
    Render, StatefulInteractiveElement as _, Styled as _, TestAppContext, VisualTestContext,
    Window, div, px,
};

use super::{
    Diff, DiffDecoration, DiffGutterMarker, DiffLinePosition, DiffLineRange, DiffSide, DiffState,
    decoration::Decorations, document::fixture,
};

fn position(side: DiffSide, line: usize) -> DiffLinePosition {
    DiffLinePosition::new("file.txt", side, line)
}

#[test]
fn decorations_cover_their_range_and_the_last_supplied_wins() {
    let red = gpui::red();
    let blue = gpui::blue();
    let decorations = Decorations::new([
        DiffDecoration::new(DiffLineRange::new("file.txt", DiffSide::Modified, 2, 4))
            .with_background(red),
        DiffDecoration::new(DiffLineRange::new("file.txt", DiffSide::Modified, 4, 4))
            .with_background(blue),
        DiffDecoration::new(
            DiffLineRange::new("cross.txt", DiffSide::Original, 8, 3)
                .with_end_side(DiffSide::Modified),
        ),
    ]);
    let background_in = |path: &str, side, line| {
        decorations
            .at(&DiffLinePosition::new(path.to_string(), side, line))
            .map(|decoration| decoration.background())
    };
    let background = |side, line| background_in("file.txt", side, line);
    assert_eq!(background(DiffSide::Modified, 1), None);
    assert_eq!(background(DiffSide::Modified, 2), Some(Some(red)));
    assert_eq!(background(DiffSide::Modified, 4), Some(Some(blue)));
    assert_eq!(background(DiffSide::Modified, 5), None);
    // A cross-side range runs from its start onwards and up to its end.
    assert_eq!(background_in("cross.txt", DiffSide::Original, 7), None);
    assert_eq!(
        background_in("cross.txt", DiffSide::Original, 9),
        Some(None)
    );
    assert_eq!(
        background_in("cross.txt", DiffSide::Modified, 3),
        Some(None)
    );
    assert_eq!(background_in("cross.txt", DiffSide::Modified, 4), None);
    assert!(
        decorations
            .at(&DiffLinePosition::new("other.txt", DiffSide::Modified, 2))
            .is_none()
    );
}

struct Host {
    state: Entity<DiffState>,
    clicked: Rc<RefCell<Vec<DiffLinePosition>>>,
}

impl Render for Host {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        let clicked = self.clicked.clone();
        div().w(px(600.)).h(px(400.)).child(
            Diff::new(&self.state)
                .size_full()
                .decorations([DiffDecoration::new(DiffLineRange::new(
                    "file.txt",
                    DiffSide::Modified,
                    1,
                    3,
                ))])
                .gutter_markers([
                    DiffGutterMarker::new("first", position(DiffSide::Modified, 2))
                        .with_label("Open comment"),
                    // A second marker on the same line is not shown.
                    DiffGutterMarker::new("second", position(DiffSide::Modified, 2)),
                ])
                .render_gutter_marker(move |marker, _, _| {
                    let clicked = clicked.clone();
                    let target = marker.position().clone();
                    let selector = format!("marker-{}", marker.id());
                    div()
                        .id(marker.id().clone())
                        .size_3()
                        .debug_selector(move || selector.clone())
                        .on_click(move |_, _, _| clicked.borrow_mut().push(target.clone()))
                }),
        )
    }
}

fn draw(cx: &mut VisualTestContext) {
    cx.run_until_parked();
    cx.update(|window, cx| {
        _ = window.draw(cx);
    });
}

#[gpui::test]
fn gutter_markers_activate_without_selecting_lines(cx: &mut TestAppContext) {
    cx.update(crate::init);
    let state = cx.new(|cx| {
        DiffState::new(
            [fixture::modified(
                "file.txt",
                "one\ntwo\nthree\n",
                "one\nTWO\nthree\n",
            )],
            cx,
        )
    });
    let clicked = Rc::new(RefCell::new(Vec::new()));
    let (_, cx) = cx.add_window_view({
        let state = state.clone();
        let clicked = clicked.clone();
        move |_, _| Host { state, clicked }
    });
    for _ in 0..3 {
        draw(cx);
    }

    assert!(cx.debug_bounds("marker-second").is_none());
    let marker = cx
        .debug_bounds("marker-first")
        .expect("the first marker on the line is shown");
    cx.simulate_click(marker.center(), Default::default());
    draw(cx);
    assert_eq!(*clicked.borrow(), [position(DiffSide::Modified, 2)]);
    assert!(cx.update(|_, cx| state.read(cx).selected_lines().is_none()));
}
