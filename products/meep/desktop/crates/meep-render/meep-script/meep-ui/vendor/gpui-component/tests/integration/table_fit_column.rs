#[cfg(feature = "gpui-fast")]
extern crate gpui_fast as gpui;

use std::{cell::RefCell, rc::Rc};

use gpui::{
    App, Context, Edges, Entity, IntoElement, Pixels, Subscription, TestAppContext, Window,
    WindowHandle, div, px,
};
use gpui_component::table::{Column, TableDelegate, TableEvent, TableState};

const FREE: usize = 0;
const CAPPED: usize = 1;
const FIXED: usize = 2;
const CAP: f32 = 120.;
/// Fractional on purpose, so the padding is rounded up as the content is.
const PADDING: f32 = 8.3;

struct FitDelegate {
    content: Option<Pixels>,
}

impl TableDelegate for FitDelegate {
    fn columns_count(&self, _: &App) -> usize {
        3
    }

    fn rows_count(&self, _: &App) -> usize {
        1
    }

    fn column(&self, col_ix: usize, _: &App) -> Column {
        let column = Column::new(format!("column-{col_ix}"), format!("Column {col_ix}"))
            .width(80.)
            .paddings(Edges {
                top: px(0.),
                right: px(PADDING),
                bottom: px(0.),
                left: px(PADDING),
            });
        match col_ix {
            CAPPED => column.max_width(CAP),
            FIXED => column.resizable(false),
            _ => column,
        }
    }

    fn render_td(
        &mut self,
        _: usize,
        _: usize,
        _: &mut Window,
        _: &mut Context<TableState<Self>>,
    ) -> impl IntoElement {
        div()
    }

    fn fit_column(
        &mut self,
        _: usize,
        _: &mut Window,
        _: &mut Context<TableState<Self>>,
    ) -> Option<Pixels> {
        self.content
    }
}

struct Table {
    window: WindowHandle<TableState<FitDelegate>>,
    widths_changed: Rc<RefCell<Vec<Vec<Pixels>>>>,
    _subscription: Subscription,
}

impl Table {
    fn new(cx: &mut TestAppContext) -> Self {
        cx.skip_drawing();
        let window =
            cx.add_window(|window, cx| TableState::new(FitDelegate { content: None }, window, cx));
        let entity: Entity<TableState<FitDelegate>> =
            window.update(cx, |_, _, cx| cx.entity()).unwrap();
        let widths_changed = Rc::new(RefCell::new(Vec::new()));
        let events = widths_changed.clone();
        let subscription = cx.update(|cx| {
            cx.subscribe(&entity, move |_, event: &TableEvent, _| {
                if let TableEvent::ColumnWidthsChanged(widths) = event {
                    events.borrow_mut().push(widths.clone());
                }
            })
        });
        Self {
            window,
            widths_changed,
            _subscription: subscription,
        }
    }

    /// Fits `col_ix` to `content` and returns the column's width afterwards
    /// with the window's scale factor.
    fn fit(&self, cx: &mut TestAppContext, col_ix: usize, content: Option<f32>) -> (Pixels, f32) {
        self.window
            .update(cx, |table, window, cx| {
                table.delegate_mut().content = content.map(px);
                table.fit_col(col_ix, window, cx);
                (table.col_width(col_ix).unwrap(), window.scale_factor())
            })
            .unwrap()
    }

    fn set_scale_factor(&self, cx: &mut TestAppContext, scale_factor: f32) {
        self.window
            .update(cx, |_, window, _| window.set_scale_factor(scale_factor))
            .unwrap();
    }

    fn col_width(&self, cx: &mut TestAppContext, col_ix: usize) -> Pixels {
        self.window
            .update(cx, |table, _, _| table.col_width(col_ix).unwrap())
            .unwrap()
    }

    fn take_events(&self) -> Vec<Vec<Pixels>> {
        self.widths_changed.take()
    }
}

#[gpui::test]
fn a_fitted_column_holds_its_content_on_whole_device_pixels(cx: &mut TestAppContext) {
    let table = Table::new(cx);

    // Fractional scales divide back inexactly, which the fit has to survive.
    for scale_factor in [1., 1.25, 1.5, 2., 3.] {
        table.set_scale_factor(cx, scale_factor);

        // One content width per tenth of a pixel, so every rounding case is hit.
        for tenth in 0..10 {
            let content = 100. + tenth as f32 / 10.;
            let (width, scale) = table.fit(cx, FREE, Some(content));
            let device_pixels = f32::from(width) * scale;

            assert!(
                width >= px(content + 2. * PADDING),
                "{content} px of content got a {width:?} column at {scale}x"
            );
            assert!(
                (device_pixels - device_pixels.round()).abs() < 1e-3,
                "{width:?} is not a whole number of device pixels at {scale}x"
            );
            assert!(
                device_pixels < (content + 2. * PADDING) * scale + 4.,
                "{content} px of content got {width:?} at {scale}x, more than rounding needs"
            );
        }
    }

    let events = table.take_events();
    assert_eq!(
        events.last().expect("a fit that changes the width emits")[FREE],
        table.col_width(cx, FREE),
        "the event carries the width the table holds"
    );
}

#[gpui::test]
fn a_fit_stays_within_the_column_and_emits_only_on_a_change(cx: &mut TestAppContext) {
    let table = Table::new(cx);
    let free = table.col_width(cx, FREE);
    let fixed = table.col_width(cx, FIXED);

    // No answer from the delegate, and a column that cannot be resized.
    assert_eq!(table.fit(cx, FREE, None).0, free);
    assert_eq!(table.fit(cx, FIXED, Some(300.)).0, fixed);
    assert!(table.take_events().is_empty());

    assert_eq!(table.fit(cx, CAPPED, Some(500.)).0, px(CAP));
    assert_eq!(table.take_events().len(), 1);

    // The same content again lands on the same width.
    let (first, _) = table.fit(cx, FREE, Some(100.45));
    table.take_events();
    let (second, _) = table.fit(cx, FREE, Some(100.45));
    assert_eq!(first, second);
    assert!(table.take_events().is_empty());
}
