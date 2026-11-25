use std::rc::Rc;

use gpui::{
    App, Bounds, ClickEvent, Corners, ElementId, InteractiveElement as _, IntoElement,
    ParentElement as _, Pixels, RenderOnce, SharedString, Styled as _, Window, canvas, deferred,
    div, prelude::FluentBuilder as _, px,
};
use gpui_base::{Placement, Positioner};

use super::handle::SurfaceHandler;
use crate::{
    ActiveTheme as _, Sizable as _, ThemeStyled as _,
    button::{Button, ButtonCustomVariant, ButtonVariants as _},
    h_flex,
    separator::Separator,
};
use gpui_base::TestSupportExt as _;

/// The height of a menu row.
const ROW_HEIGHT: Pixels = px(32.);

/// One command in the edit menu.
pub(crate) struct EditMenuItem {
    label: SharedString,
    on_click: Rc<dyn Fn(&mut Window, &mut App)>,
}

impl EditMenuItem {
    pub(crate) fn new(
        label: impl Into<SharedString>,
        on_click: impl Fn(&mut Window, &mut App) + 'static,
    ) -> Self {
        Self {
            label: label.into(),
            on_click: Rc::new(on_click),
        }
    }
}

/// The row of commands a touch selection offers: Cut, Copy, Paste, Select All
/// — whichever apply. It floats above the selection, or below it when there
/// is no room above, and stays out of the way of the handles' knobs.
///
/// Every item is a [`Button`] sized for a finger, so the row keeps the button
/// family's press feedback. It carries no arrow: it belongs to the selection
/// it sits on, not to a trigger.
#[derive(IntoElement)]
pub(crate) struct EditMenu {
    id: ElementId,
    /// The selection, including the room its handles take.
    anchor: Bounds<Pixels>,
    items: Vec<EditMenuItem>,
    on_paint: Option<SurfaceHandler>,
}

impl EditMenu {
    pub(crate) fn new(id: impl Into<ElementId>, anchor: Bounds<Pixels>) -> Self {
        Self {
            id: id.into(),
            anchor,
            items: Vec::new(),
            on_paint: None,
        }
    }

    pub(crate) fn items(mut self, items: impl IntoIterator<Item = EditMenuItem>) -> Self {
        self.items.extend(items);
        self
    }

    pub(crate) fn on_paint(mut self, on_paint: SurfaceHandler) -> Self {
        self.on_paint = Some(on_paint);
        self
    }
}

impl RenderOnce for EditMenu {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let id = self.id;
        let on_paint = self.on_paint;
        // A pill-like bar, as iOS draws its edit menu.
        let radius = cx.theme().radius_lg;
        // The menu family's hover, not the ghost button's: the ghost's grey
        // is the bar's own ring color and would blur the edge.
        let item_style = ButtonCustomVariant::new(cx)
            .color(cx.theme().transparent)
            .foreground(cx.theme().popover_foreground)
            .hover(cx.theme().accent)
            .active(cx.theme().accent);
        let last = self.items.len().saturating_sub(1);
        let items = self.items.into_iter().enumerate().flat_map(|(ix, item)| {
            let on_click = item.on_click;
            // The items fill the bar edge to edge, so each one's press
            // surface takes the bar's own corners: the first the left pair,
            // the last the right pair, the ones between none.
            let corners = Corners {
                top_left: ix == 0,
                bottom_left: ix == 0,
                top_right: ix == last,
                bottom_right: ix == last,
            };
            // Observed under its label, so a test can press "Copy".
            let button = div()
                .id(item.label.clone())
                .test_support()
                .child(
                    Button::new(ix)
                        .custom(item_style)
                        // This is a finger's menu wherever it shows: body
                        // text in a 32px row.
                        .large()
                        .h(ROW_HEIGHT)
                        .px_3()
                        .rounded(radius)
                        .border_corners(corners)
                        .tab_stop(false)
                        .label(item.label)
                        .on_click(move |_: &ClickEvent, window, cx| on_click(window, cx)),
                )
                .into_any_element();
            // A rule between neighbours, none before the first, the full
            // height of the bar.
            (ix > 0)
                .then(|| Separator::vertical().into_any_element())
                .into_iter()
                .chain([button])
        });
        deferred(
            Positioner::side(self.anchor)
                .placement(Placement::Top)
                .offset(px(8.))
                .occlude()
                .child(
                    h_flex()
                        .id(id)
                        .relative()
                        .items_stretch()
                        .overflow_hidden()
                        .popover_style(cx)
                        .rounded(radius)
                        .children(items)
                        .when_some(on_paint, |this, on_paint| {
                            this.child(
                                canvas(
                                    move |bounds, window, cx| on_paint(bounds, window, cx),
                                    |_, _, _, _| {},
                                )
                                .absolute()
                                .inset_0(),
                            )
                        }),
                ),
        )
        .with_priority(gpui_base::POPUP_PRIORITY)
    }
}
