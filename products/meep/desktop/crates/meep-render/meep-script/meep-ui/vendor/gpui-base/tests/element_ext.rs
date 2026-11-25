#[cfg(feature = "gpui-fast")]
extern crate gpui_fast as gpui;

use std::{cell::RefCell, rc::Rc};

use gpui::{Context, IntoElement, Render, Styled as _, TestAppContext, Window, div, px};
use gpui_base::ElementExt as _;

struct PrepaintHarness {
    captured: Rc<RefCell<Option<gpui::Bounds<gpui::Pixels>>>>,
}

impl Render for PrepaintHarness {
    fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
        let captured = self.captured.clone();
        div()
            .size(px(80.))
            .p(px(10.))
            .on_prepaint(move |bounds, _, _| *captured.borrow_mut() = Some(bounds))
    }
}

#[gpui::test]
fn prepaint_callback_observes_the_parent_bounds(cx: &mut TestAppContext) {
    let captured = Rc::new(RefCell::new(None));
    let result = captured.clone();
    let (_, cx) = cx.add_window_view(move |_, _| PrepaintHarness { captured });

    cx.update(|window, cx| window.draw(cx).clear(cx));

    let bounds = result.borrow().expect("prepaint callback should run");
    assert_eq!(bounds.origin, gpui::point(px(0.), px(0.)));
    assert_eq!(bounds.size.width, px(80.));
    assert_eq!(bounds.size.height, px(80.));
}
