use crate::TestSupportExt as _;
use std::rc::Rc;

use gpui::{
    AnyElement, App, ClickEvent, Div, ElementId, InteractiveElement, Interactivity, IntoElement,
    ParentElement, RenderOnce, Role, StatefulInteractiveElement, StyleRefinement, Styled, Window,
    div, prelude::FluentBuilder as _,
};
use smallvec::SmallVec;

use crate::StyledExt as _;

type ChangeHandler = Rc<dyn Fn(bool, &ClickEvent, &mut Window, &mut App)>;

/// An unstyled accordion root for application-owned items.
#[derive(IntoElement)]
pub struct Accordion {
    base: crate::ObservedElement<gpui::Stateful<Div>>,
    style: StyleRefinement,
    children: SmallVec<[AnyElement; 2]>,
}

impl Accordion {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            base: div().id(id).test_support(),
            style: StyleRefinement::default(),
            children: SmallVec::new(),
        }
    }
}

impl Styled for Accordion {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for Accordion {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl InteractiveElement for Accordion {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }

    fn track_focus(mut self, handle: &gpui::FocusHandle) -> Self {
        self.base = self.base.track_focus(handle);
        self
    }
}

impl StatefulInteractiveElement for Accordion {}

impl RenderOnce for Accordion {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base
            .role(Role::Group)
            .children(self.children)
            .refine_style(&self.style)
    }
}

/// An unstyled accordion item connecting one trigger with its panel content.
#[derive(IntoElement)]
pub struct AccordionItem {
    base: Div,
    style: StyleRefinement,
    open: bool,
    disabled: bool,
    header: Option<AccordionHeader>,
    panel: Option<AccordionPanel>,
    children: SmallVec<[AnyElement; 2]>,
}

impl AccordionItem {
    pub fn new() -> Self {
        Self {
            base: div(),
            style: StyleRefinement::default(),
            open: false,
            disabled: false,
            header: None,
            panel: None,
            children: SmallVec::new(),
        }
    }
    pub fn open(mut self, open: bool) -> Self {
        self.open = open;
        self
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    pub fn header(mut self, header: AccordionHeader) -> Self {
        self.header = Some(header);
        self
    }

    pub fn panel(mut self, panel: AccordionPanel) -> Self {
        self.panel = Some(panel);
        self
    }
}

impl Styled for AccordionItem {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for AccordionItem {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for AccordionItem {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base
            .when_some(self.header, |this, header| {
                this.child(header.open(self.open).disabled(self.disabled))
            })
            .when_some(self.panel, |this, panel| this.child(panel.open(self.open)))
            .children(self.children)
            .refine_style(&self.style)
    }
}

/// An unstyled heading that owns the trigger for one accordion item.
#[derive(IntoElement)]
pub struct AccordionHeader {
    id: Option<ElementId>,
    style: StyleRefinement,
    level: usize,
    trigger: AccordionTrigger,
    children: SmallVec<[AnyElement; 1]>,
}

impl AccordionHeader {
    pub fn new(trigger: AccordionTrigger) -> Self {
        Self {
            id: None,
            style: StyleRefinement::default(),
            level: 3,
            trigger,
            children: SmallVec::new(),
        }
    }
    pub fn level(mut self, level: usize) -> Self {
        self.level = level;
        self
    }

    pub fn id(mut self, id: impl Into<ElementId>) -> Self {
        self.id = Some(id.into());
        self
    }
    fn open(mut self, open: bool) -> Self {
        self.trigger = self.trigger.open(open);
        self
    }

    fn disabled(mut self, disabled: bool) -> Self {
        self.trigger = self.trigger.disabled(disabled);
        self
    }
}

impl Styled for AccordionHeader {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for AccordionHeader {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for AccordionHeader {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let content = div()
            .child(self.trigger)
            .children(self.children)
            .refine_style(&self.style);
        match self.id {
            Some(id) => content
                .id(id)
                .test_support()
                .role(Role::Heading)
                .aria_level(self.level)
                .into_any_element(),
            None => content.into_any_element(),
        }
    }
}

/// An unstyled accordion panel with controlled mounting.
#[derive(IntoElement)]
pub struct AccordionPanel {
    id: Option<ElementId>,
    style: StyleRefinement,
    open: bool,
    keep_mounted: bool,
    children: SmallVec<[AnyElement; 2]>,
}

impl AccordionPanel {
    pub fn new() -> Self {
        Self {
            id: None,
            style: StyleRefinement::default(),
            open: false,
            keep_mounted: false,
            children: SmallVec::new(),
        }
    }

    pub fn open(mut self, open: bool) -> Self {
        self.open = open;
        self
    }

    pub fn keep_mounted(mut self, keep_mounted: bool) -> Self {
        self.keep_mounted = keep_mounted;
        self
    }

    pub fn id(mut self, id: impl Into<ElementId>) -> Self {
        self.id = Some(id.into());
        self
    }
}

impl Styled for AccordionPanel {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for AccordionPanel {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl RenderOnce for AccordionPanel {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        if !self.open && !self.keep_mounted {
            return gpui::Empty.into_any_element();
        }

        let content = div().children(self.children).refine_style(&self.style);
        match self.id {
            Some(id) => content
                .id(id)
                .test_support()
                .role(Role::Region)
                .into_any_element(),
            None => content.into_any_element(),
        }
    }
}

/// An unstyled accordion trigger with controlled expanded state.
///
/// The application owns the title, disclosure icon, content, layout, and
/// animation. Activating the trigger requests the opposite of `open`.
#[derive(IntoElement)]
pub struct AccordionTrigger {
    base: crate::ObservedElement<gpui::Stateful<Div>>,
    style: StyleRefinement,
    children: SmallVec<[AnyElement; 2]>,
    open: bool,
    disabled: bool,
    on_change: Option<ChangeHandler>,
}

impl AccordionTrigger {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            base: div().id(id).test_support(),
            style: StyleRefinement::default(),
            children: SmallVec::new(),
            open: false,
            disabled: false,
            on_change: None,
        }
    }

    pub fn open(mut self, open: bool) -> Self {
        self.open = open;
        self
    }

    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Handles a requested change to the controlled expanded state.
    pub fn on_change(
        mut self,
        handler: impl Fn(bool, &ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_change = Some(Rc::new(handler));
        self
    }
}

impl Styled for AccordionTrigger {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for AccordionTrigger {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl InteractiveElement for AccordionTrigger {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }

    fn track_focus(mut self, handle: &gpui::FocusHandle) -> Self {
        self.base = self.base.track_focus(handle);
        self
    }
}

impl StatefulInteractiveElement for AccordionTrigger {}

impl RenderOnce for AccordionTrigger {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let next_open = !self.open;

        self.base
            .role(Role::Button)
            .aria_expanded(self.open)
            .when_some(
                (!self.disabled).then_some(self.on_change).flatten(),
                move |this, on_change| {
                    this.on_click(move |event, window, cx| on_change(next_open, event, window, cx))
                },
            )
            .children(self.children)
            .refine_style(&self.style)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{cell::RefCell, rc::Rc};

    use gpui::{
        Context, Element as _, Modifiers, Render, Role, VisualTestContext, accesskit, canvas,
        point, px,
    };

    #[gpui::test]
    fn trigger_projects_expanded_accessibility_state(cx: &mut gpui::TestAppContext) {
        let requested = Rc::new(RefCell::new(Vec::new()));
        let captured = Rc::new(RefCell::new(None));

        struct Probe {
            requested: Rc<RefCell<Vec<bool>>>,
            captured: Rc<RefCell<Option<accesskit::Node>>>,
        }

        impl Render for Probe {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let requested = self.requested.clone();
                let captured = self.captured.clone();
                canvas(
                    move |_, window, cx| {
                        let mut node = accesskit::Node::new(Role::Button);
                        AccordionTrigger::new("trigger")
                            .open(true)
                            .on_change(move |open, _, _, _| requested.borrow_mut().push(open))
                            .render(window, cx)
                            .into_element()
                            .write_a11y_info(&mut node);
                        *captured.borrow_mut() = Some(node);
                    },
                    |_, _, _, _| {},
                )
            }
        }

        let (_, window) = cx.add_window_view({
            let requested = requested.clone();
            let captured = captured.clone();
            move |_, _| Probe {
                requested,
                captured,
            }
        });
        window.update(|window, cx| window.draw(cx).clear(cx));

        let node = captured.borrow_mut().take().unwrap();
        assert_eq!(node.role(), Role::Button);
        assert_eq!(node.is_expanded(), Some(true));

        assert!(requested.borrow().is_empty());
    }

    struct TriggerHarness {
        open: bool,
        disabled: bool,
        requested: Rc<RefCell<Vec<bool>>>,
    }

    impl Render for TriggerHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let requested = self.requested.clone();
            AccordionTrigger::new("trigger")
                .open(self.open)
                .disabled(self.disabled)
                .size(px(100.))
                .on_change(move |open, _, _, _| requested.borrow_mut().push(open))
        }
    }

    fn harness(
        cx: &mut gpui::TestAppContext,
        open: bool,
        disabled: bool,
    ) -> (&mut VisualTestContext, Rc<RefCell<Vec<bool>>>) {
        let requested = Rc::new(RefCell::new(Vec::new()));
        let (_, cx) = cx.add_window_view({
            let requested = requested.clone();
            move |_, _| TriggerHarness {
                open,
                disabled,
                requested,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (cx, requested)
    }

    #[gpui::test]
    fn pointer_requests_next_controlled_state_and_respects_disabled(cx: &mut gpui::TestAppContext) {
        let (cx, requested) = harness(cx, false, false);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        assert_eq!(&*requested.borrow(), &[true]);

        let (cx, requested) = harness(cx, true, true);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        assert!(requested.borrow().is_empty());
    }

    #[gpui::test]
    fn header_and_panel_project_structural_roles(cx: &mut gpui::TestAppContext) {
        let captured = Rc::new(RefCell::new(Vec::new()));

        struct Probe(Rc<RefCell<Vec<accesskit::Node>>>);

        impl Render for Probe {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let captured = self.0.clone();
                canvas(
                    move |_, window, cx| {
                        let mut header_node = accesskit::Node::new(Role::Heading);
                        AccordionHeader::new(AccordionTrigger::new("trigger"))
                            .id("header")
                            .level(2)
                            .render(window, cx)
                            .into_element()
                            .write_a11y_info(&mut header_node);

                        let mut panel_node = accesskit::Node::new(Role::Region);
                        AccordionPanel::new()
                            .id("panel")
                            .open(true)
                            .render(window, cx)
                            .into_element()
                            .write_a11y_info(&mut panel_node);
                        *captured.borrow_mut() = vec![header_node, panel_node];
                    },
                    |_, _, _, _| {},
                )
            }
        }

        let (_, view) = cx.add_window_view({
            let captured = captured.clone();
            move |_, _| Probe(captured)
        });
        view.update(|window, cx| window.draw(cx).clear(cx));
        let nodes = captured.borrow();
        assert_eq!(nodes[0].role(), Role::Heading);
        assert_eq!(nodes[1].role(), Role::Region);
    }
}
