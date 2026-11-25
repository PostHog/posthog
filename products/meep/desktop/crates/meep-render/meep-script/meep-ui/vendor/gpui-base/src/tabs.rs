use std::rc::Rc;

use gpui::{
    AnyElement, App, ClickEvent, Div, ElementId, InteractiveElement, Interactivity, IntoElement,
    MouseButton, ParentElement, Refineable as _, RenderOnce, Role, SharedString,
    StatefulInteractiveElement, StyleRefinement, Styled, Window, div, prelude::FluentBuilder as _,
    relative,
};
use smallvec::SmallVec;

use crate::{StateStyle, StyledExt as _, TestSupportExt as _, a11y_disabled::A11yDisabledExt as _};

type ClickHandler = Rc<dyn Fn(&ClickEvent, &mut Window, &mut App)>;

/// An unstyled tab that owns pointer activation and accessibility behavior.
///
/// Tabs do not participate in keyboard focus by themselves. A compound tab
/// list may add keyboard navigation when that behavior is introduced.
// TODO: Add compound keyboard navigation with roving focus, arrow keys,
// Home/End, and Enter/Space activation before treating Tabs as a complete
// desktop tab-list primitive.
#[derive(IntoElement)]
pub struct Tab {
    id: ElementId,
    base: Div,
    style: StyleRefinement,
    semantic_styles: TabStyles,
    selected: bool,
    disabled: bool,
    children: SmallVec<[AnyElement; 2]>,
    on_click: Option<ClickHandler>,
    accessibility_label: Option<SharedString>,
    position_in_set: Option<usize>,
    size_of_set: Option<usize>,
}

impl Tab {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            base: div(),
            style: StyleRefinement::default(),
            semantic_styles: TabStyles::default(),
            selected: false,
            disabled: false,
            children: SmallVec::new(),
            on_click: None,
            accessibility_label: None,
            position_in_set: None,
            size_of_set: None,
        }
    }

    /// Updates the element identity used when the tab is rendered.
    pub fn id(mut self, id: impl Into<ElementId>) -> Self {
        self.id = id.into();
        self
    }

    pub fn selected(mut self, selected: bool) -> Self {
        self.selected = selected;
        self
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }

    /// Sets this tab's one-based position and the tab list's total size, so
    /// assistive technology can announce "tab 2 of 5".
    pub fn set_position(mut self, position: usize, size: usize) -> Self {
        self.position_in_set = Some(position);
        self.size_of_set = Some(size);
        self
    }

    pub fn on_click(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_click = Some(Rc::new(handler));
        self
    }

    pub fn styles(mut self, build: impl FnOnce(TabStyles) -> TabStyles) -> Self {
        self.semantic_styles = build(self.semantic_styles);
        self
    }

    fn resolved_style(&self) -> StyleRefinement {
        crate::state_style::resolve_style(
            &self.style,
            [
                self.selected.then_some(&self.semantic_styles.selected),
                self.disabled.then_some(&self.semantic_styles.disabled),
            ]
            .into_iter()
            .flatten(),
        )
    }
}

#[derive(Default)]
pub struct TabStyles {
    selected: StyleRefinement,
    disabled: StyleRefinement,
}

impl TabStyles {
    pub fn selected(mut self, build: impl FnOnce(StateStyle) -> StateStyle) -> Self {
        self.selected
            .refine(&build(StateStyle::default()).into_refinement());
        self
    }

    pub fn disabled(mut self, build: impl FnOnce(StateStyle) -> StateStyle) -> Self {
        self.disabled
            .refine(&build(StateStyle::default()).into_refinement());
        self
    }
}

impl Styled for Tab {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for Tab {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl InteractiveElement for Tab {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for Tab {}

impl RenderOnce for Tab {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let disabled = self.disabled;
        let style = self.resolved_style();

        self.base
            .id(self.id)
            .test_support()
            .role(Role::Tab)
            // Match Button's neutral control geometry: a fixed-size tab
            // centers ordinary content, while callers still own its size,
            // spacing and visual treatment.
            .flex()
            .items_center()
            .justify_center()
            .line_height(relative(1.))
            .when_some(self.accessibility_label, |this, label| {
                this.aria_label(label)
            })
            .aria_selected(self.selected)
            .when_some(self.position_in_set, |this, position| {
                this.aria_position_in_set(position)
            })
            .when_some(self.size_of_set, |this, size| this.aria_size_of_set(size))
            .on_mouse_down(MouseButton::Left, |_, _, cx| cx.stop_propagation())
            .when_some(
                (!disabled).then_some(self.on_click).flatten(),
                |this, on_click| {
                    this.on_click(move |event, window, cx| on_click(event, window, cx))
                },
            )
            .children(self.children)
            .refine_style(&style)
            .a11y_disabled(disabled)
    }
}

/// An unstyled collection root for [`Tab`] elements.
///
/// Controlled selection and activation are expressed directly by its child
/// tabs. The root supplies collection accessibility without introducing a
/// context hierarchy or new keyboard behavior.
#[derive(IntoElement)]
pub struct Tabs {
    base: gpui::Stateful<Div>,
    style: StyleRefinement,
    children: SmallVec<[AnyElement; 2]>,
}

impl Tabs {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            base: div().id(id),
            style: StyleRefinement::default(),
            children: SmallVec::new(),
        }
    }
}

impl Styled for Tabs {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for Tabs {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl InteractiveElement for Tabs {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for Tabs {}

impl RenderOnce for Tabs {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base
            .role(Role::TabList)
            .children(self.children)
            .refine_style(&self.style)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ElementExt as _;
    use std::{
        cell::Cell,
        rc::Rc,
        sync::{Arc, Mutex},
    };

    use gpui::{
        Context, Element as _, Modifiers, Render, Role, VisualTestContext, accesskit, canvas, hsla,
        point, px,
    };

    struct TabHarness {
        disabled: bool,
        clicks: Rc<Cell<usize>>,
    }

    impl Render for TabHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let clicks = self.clicks.clone();
            Tab::new("tab")
                .disabled(self.disabled)
                .size(px(100.))
                .on_click(move |_, _, _| clicks.set(clicks.get() + 1))
        }
    }

    fn harness(
        cx: &mut gpui::TestAppContext,
        disabled: bool,
    ) -> (&mut VisualTestContext, Rc<Cell<usize>>) {
        let clicks = Rc::new(Cell::new(0));
        let (_, cx) = cx.add_window_view({
            let clicks = clicks.clone();
            move |_, _| TabHarness { disabled, clicks }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (cx, clicks)
    }

    #[gpui::test]
    fn pointer_activation_and_disabled_gating_match_tabs(cx: &mut gpui::TestAppContext) {
        let (cx, clicks) = harness(cx, false);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        assert_eq!(clicks.get(), 1);

        let (cx, clicks) = harness(cx, true);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        assert_eq!(clicks.get(), 0);
    }

    #[gpui::test]
    fn fixed_height_tab_centers_ordinary_child_geometry(cx: &mut gpui::TestAppContext) {
        type Captured = Arc<
            Mutex<(
                Option<gpui::Bounds<gpui::Pixels>>,
                Option<gpui::Bounds<gpui::Pixels>>,
            )>,
        >;

        struct AlignmentProbe(Captured);

        impl Render for AlignmentProbe {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let root_capture = self.0.clone();
                let child_capture = self.0.clone();
                Tab::new("alignment-tab")
                    .w(px(120.))
                    .h(px(40.))
                    .child(
                        div()
                            .w(px(48.))
                            .h(px(12.))
                            .on_prepaint(move |bounds, _, _| {
                                child_capture.lock().unwrap().1 = Some(bounds);
                            }),
                    )
                    .on_prepaint(move |bounds, _, _| {
                        root_capture.lock().unwrap().0 = Some(bounds);
                    })
            }
        }

        let captured = Arc::new(Mutex::new((None, None)));
        let (_, context) = cx.add_window_view({
            let captured = captured.clone();
            move |_, _| AlignmentProbe(captured)
        });
        context.update(|window, cx| window.draw(cx).clear(cx));

        let (root, child) = *captured.lock().unwrap();
        assert_eq!(
            child.expect("child bounds").center(),
            root.expect("tab bounds").center()
        );
    }

    #[gpui::test]
    fn exposes_tab_accessibility_state(cx: &mut gpui::TestAppContext) {
        type Captured = Arc<Mutex<Option<(accesskit::Node, accesskit::Node)>>>;

        struct Probe(Captured);

        impl Render for Probe {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let captured = self.0.clone();
                canvas(
                    move |_, window, cx| {
                        let mut info = |tab: Tab| {
                            let mut node = accesskit::Node::new(Role::Tab);
                            tab.render(window, cx)
                                .into_element()
                                .write_a11y_info(&mut node);
                            node
                        };
                        let selected = info(
                            Tab::new("selected")
                                .selected(true)
                                .accessibility_label("Account")
                                .on_click(|_, _, _| {}),
                        );
                        let disabled =
                            info(Tab::new("disabled").disabled(true).on_click(|_, _, _| {}));
                        *captured.lock().unwrap() = Some((selected, disabled));
                    },
                    |_, _, _, _| {},
                )
            }
        }

        let captured: Captured = Arc::new(Mutex::new(None));
        let result = captured.clone();
        let (_, cx) = cx.add_window_view(move |_, _| Probe(captured));
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let (selected, disabled) = result.lock().unwrap().take().unwrap();

        assert_eq!(selected.role(), Role::Tab);
        assert_eq!(selected.label(), Some("Account"));
        assert_eq!(selected.is_selected(), Some(true));
        assert!(selected.supports_action(accesskit::Action::Click));
        assert!(!disabled.supports_action(accesskit::Action::Click));
    }

    #[gpui::test]
    fn semantic_styles_preserve_the_legacy_state_priority(_cx: &mut gpui::TestAppContext) {
        let expected = hsla(0.3, 0.4, 0.5, 1.0);
        let mut tab = Tab::new("tab")
            .selected(true)
            .disabled(true)
            .styles(|styles| {
                styles
                    .selected(|style| style.opacity(0.8))
                    .disabled(|style| style.opacity(0.5))
            })
            .opacity(0.9);

        assert_eq!(tab.resolved_style().opacity, Some(0.5));
        tab.style().background = Some(expected.into());
        assert_eq!(tab.resolved_style().background, Some(expected.into()));
    }

    #[gpui::test]
    fn tabs_exposes_tab_list_role(cx: &mut gpui::TestAppContext) {
        type Captured = Arc<Mutex<Option<accesskit::Node>>>;
        struct Probe(Captured);

        impl Render for Probe {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let captured = self.0.clone();
                canvas(
                    move |_, window, cx| {
                        let mut node = accesskit::Node::new(Role::TabList);
                        Tabs::new("tabs")
                            .render(window, cx)
                            .into_element()
                            .write_a11y_info(&mut node);
                        *captured.lock().unwrap() = Some(node);
                    },
                    |_, _, _, _| {},
                )
            }
        }

        let captured: Captured = Arc::new(Mutex::new(None));
        let result = captured.clone();
        let (_, cx) = cx.add_window_view(move |_, _| Probe(captured));
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert_eq!(result.lock().unwrap().take().unwrap().role(), Role::TabList);
    }
}
