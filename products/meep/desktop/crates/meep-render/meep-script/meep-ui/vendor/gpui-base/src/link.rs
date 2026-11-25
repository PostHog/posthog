use std::rc::Rc;

use gpui::{
    AnyElement, App, ClickEvent, Div, ElementId, FocusHandle, InteractiveElement, Interactivity,
    IntoElement, MouseButton, ParentElement, Refineable as _, RenderOnce, Role, SharedString,
    Stateful, StatefulInteractiveElement, StyleRefinement, Styled, Window, div,
    prelude::FluentBuilder as _,
};
use smallvec::SmallVec;

use crate::{StateStyle, StyledExt as _, a11y_disabled::A11yDisabledExt as _};

type ActivationHandler = Rc<dyn Fn(&ClickEvent, &mut Window, &mut App)>;
type OpenHandler = Rc<dyn Fn(&str, &ClickEvent, &mut Window, &mut App)>;

/// An unstyled link that owns focus, activation, and accessibility semantics.
///
/// `href` is target data, not an instruction to launch a browser. Applications
/// inject navigation through [`Link::open_with`], allowing internal routes,
/// embedded web views, and external browsers to share the same behavior module.
/// `href` is also not rendered as text; applications provide visible content
/// through the element's child slot.
#[derive(IntoElement)]
pub struct Link {
    id: ElementId,
    base: Stateful<Div>,
    style: StyleRefinement,
    semantic_styles: LinkStyles,
    href: Option<SharedString>,
    disabled: bool,
    children: SmallVec<[AnyElement; 2]>,
    on_activate: Option<ActivationHandler>,
    open_with: Option<OpenHandler>,
    accessibility_label: Option<SharedString>,
    tab_index: isize,
    tab_stop: bool,
}

/// Semantic root styles supported by [`Link`].
#[derive(Default)]
pub struct LinkStyles {
    disabled: StyleRefinement,
}

impl LinkStyles {
    pub fn disabled(mut self, build: impl FnOnce(StateStyle) -> StateStyle) -> Self {
        self.disabled
            .refine(&build(StateStyle::default()).into_refinement());
        self
    }
}

impl Link {
    pub fn new(id: impl Into<ElementId>) -> Self {
        let id = id.into();
        Self {
            base: div().id(id.clone()),
            id,
            style: StyleRefinement::default(),
            semantic_styles: LinkStyles::default(),
            href: None,
            disabled: false,
            children: SmallVec::new(),
            on_activate: None,
            open_with: None,
            accessibility_label: None,
            tab_index: 0,
            tab_stop: true,
        }
    }

    /// Sets the application-defined navigation target.
    pub fn href(mut self, href: impl Into<SharedString>) -> Self {
        self.href = Some(href.into());
        self
    }

    /// Injects the strategy used to open `href` on activation.
    ///
    /// Base never calls [`App::open_url`] on its own.
    pub fn open_with(
        mut self,
        open: impl Fn(&str, &ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.open_with = Some(Rc::new(open));
        self
    }

    /// Observes pointer or keyboard activation after the open strategy runs.
    pub fn on_activate(
        mut self,
        handler: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_activate = Some(Rc::new(handler));
        self
    }

    /// Sets whether pointer and keyboard activation are ignored.
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Configures application-owned styles for the link's semantic states.
    pub fn styles(mut self, build: impl FnOnce(LinkStyles) -> LinkStyles) -> Self {
        self.semantic_styles = build(self.semantic_styles);
        self
    }

    fn resolved_style(&self) -> StyleRefinement {
        crate::state_style::resolve_style(
            &self.style,
            self.disabled.then_some(&self.semantic_styles.disabled),
        )
    }

    /// Sets the name exposed to accessibility clients.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.accessibility_label = Some(label.into());
        self
    }

    /// Sets the focus traversal index. Use this within a GPUI tab group.
    pub fn tab_index(mut self, tab_index: isize) -> Self {
        self.tab_index = tab_index;
        self
    }

    /// Sets whether the link participates in keyboard focus traversal.
    pub fn tab_stop(mut self, tab_stop: bool) -> Self {
        self.tab_stop = tab_stop;
        self
    }

    fn focus_handle(&self, window: &mut Window, cx: &mut App) -> FocusHandle {
        window
            .use_keyed_state(self.id.clone(), cx, |_, cx| cx.focus_handle())
            .read(cx)
            .clone()
    }
}

impl Styled for Link {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl ParentElement for Link {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl InteractiveElement for Link {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for Link {}

impl RenderOnce for Link {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let focus_handle = self.focus_handle(window, cx);
        let disabled = self.disabled;
        let style = self.resolved_style();
        let href = self.href;
        let open_with = self.open_with;
        let on_activate = self.on_activate;
        let activates = on_activate.is_some() || href.is_some() && open_with.is_some();

        self.base
            .role(Role::Link)
            .when_some(self.accessibility_label, |this, label| {
                this.aria_label(label)
            })
            .when(!disabled, |this| {
                this.track_focus(
                    &focus_handle
                        .tab_index(self.tab_index)
                        .tab_stop(self.tab_stop),
                )
            })
            .when(disabled, |this| {
                this.on_mouse_down(MouseButton::Left, |_, _, cx| {
                    cx.stop_propagation();
                })
            })
            .when(!disabled && activates, |this| {
                this.on_click(move |event, window, cx| {
                    if let (Some(href), Some(open)) = (&href, &open_with) {
                        open(href.as_ref(), event, window, cx);
                    }
                    if let Some(on_activate) = &on_activate {
                        on_activate(event, window, cx);
                    }
                })
            })
            .children(self.children)
            .refine_style(&style)
            .a11y_disabled(disabled)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        cell::{Cell, RefCell},
        rc::Rc,
        sync::{Arc, Mutex},
    };

    use gpui::{
        Context, Element as _, KeyDownEvent, KeyUpEvent, Keystroke, Modifiers, Render,
        TestAppContext, VisualTestContext, accesskit, canvas, point, px,
    };

    struct LinkHarness {
        disabled: bool,
        activations: Rc<Cell<usize>>,
        keyboard_events: Rc<Cell<usize>>,
        opened: Rc<RefCell<Vec<String>>>,
        parent_clicks: Rc<Cell<usize>>,
    }

    impl Render for LinkHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let activations = self.activations.clone();
            let keyboard_events = self.keyboard_events.clone();
            let opened = self.opened.clone();
            let parent_clicks = self.parent_clicks.clone();

            div()
                .id("link-parent")
                .tab_group()
                .size(px(100.))
                .on_click(move |_, _, _| parent_clicks.set(parent_clicks.get() + 1))
                .child(
                    Link::new("link")
                        .href("app://settings")
                        .disabled(self.disabled)
                        .size_full()
                        .open_with(move |href, _, _, _| {
                            opened.borrow_mut().push(href.to_owned());
                        })
                        .on_activate(move |event, _, _| {
                            activations.set(activations.get() + 1);
                            if matches!(event, ClickEvent::Keyboard(_)) {
                                keyboard_events.set(keyboard_events.get() + 1);
                            }
                        }),
                )
        }
    }

    fn harness(
        cx: &mut TestAppContext,
        disabled: bool,
    ) -> (
        &mut VisualTestContext,
        Rc<Cell<usize>>,
        Rc<Cell<usize>>,
        Rc<RefCell<Vec<String>>>,
        Rc<Cell<usize>>,
    ) {
        let activations = Rc::new(Cell::new(0));
        let keyboard_events = Rc::new(Cell::new(0));
        let opened = Rc::new(RefCell::new(Vec::new()));
        let parent_clicks = Rc::new(Cell::new(0));
        let (_, cx) = cx.add_window_view({
            let activations = activations.clone();
            let keyboard_events = keyboard_events.clone();
            let opened = opened.clone();
            let parent_clicks = parent_clicks.clone();
            move |_, _| LinkHarness {
                disabled,
                activations,
                keyboard_events,
                opened,
                parent_clicks,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (cx, activations, keyboard_events, opened, parent_clicks)
    }

    fn activate_key(cx: &mut VisualTestContext, key: &str) {
        let keystroke =
            cx.update(|_, cx| Keystroke::parse_with_os(key, cx.platform_info().os).unwrap());
        cx.simulate_event(KeyDownEvent {
            keystroke: keystroke.clone(),
            is_held: false,
            prefer_character_input: false,
        });
        cx.simulate_event(KeyUpEvent { keystroke });
    }

    #[gpui::test]
    fn pointer_runs_injected_open_strategy_and_activation_once(cx: &mut TestAppContext) {
        let (cx, activations, keyboard_events, opened, _) = harness(cx, false);

        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());

        assert_eq!(activations.get(), 1);
        assert_eq!(keyboard_events.get(), 0);
        assert_eq!(&*opened.borrow(), &["app://settings"]);
        assert_eq!(cx.opened_url(), None);
    }

    #[gpui::test]
    fn open_strategy_runs_before_activation_callback(cx: &mut TestAppContext) {
        struct OrderedLink(Rc<RefCell<Vec<&'static str>>>);

        impl Render for OrderedLink {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let opened = self.0.clone();
                let activated = self.0.clone();
                Link::new("ordered-link")
                    .href("app://ordered")
                    .size(px(100.))
                    .open_with(move |_, _, _, _| opened.borrow_mut().push("open"))
                    .on_activate(move |_, _, _| activated.borrow_mut().push("activate"))
            }
        }

        let order = Rc::new(RefCell::new(Vec::new()));
        let result = order.clone();
        let (_, cx) = cx.add_window_view(move |_, _| OrderedLink(order));
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());

        assert_eq!(result.borrow().as_slice(), &["open", "activate"]);
    }

    #[gpui::test]
    fn enter_and_space_each_activate_once(cx: &mut TestAppContext) {
        let (cx, activations, keyboard_events, opened, _) = harness(cx, false);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        activations.set(0);
        opened.borrow_mut().clear();
        cx.update(|window, cx| {
            assert!(window.focused(cx).is_some());
            window.draw(cx).clear(cx);
        });

        activate_key(cx, "enter");
        activate_key(cx, "space");

        assert_eq!(activations.get(), 2);
        assert_eq!(keyboard_events.get(), 2);
        assert_eq!(&*opened.borrow(), &["app://settings", "app://settings"]);
        assert_eq!(cx.opened_url(), None);
    }

    #[gpui::test]
    fn href_without_strategy_never_opens_externally(cx: &mut TestAppContext) {
        struct TargetOnly;

        impl Render for TargetOnly {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                Link::new("target-only")
                    .href("https://example.com")
                    .size(px(100.))
            }
        }

        let (_, cx) = cx.add_window_view(|_, _| TargetOnly);
        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        assert_eq!(cx.opened_url(), None);
    }

    #[gpui::test]
    fn disabled_link_is_inert_and_blocks_parent_activation(cx: &mut TestAppContext) {
        let (cx, activations, _, opened, parent_clicks) = harness(cx, true);

        cx.simulate_click(point(px(10.), px(10.)), Modifiers::default());
        activate_key(cx, "enter");
        activate_key(cx, "space");

        assert_eq!(activations.get(), 0);
        assert!(opened.borrow().is_empty());
        assert_eq!(parent_clicks.get(), 0);
    }

    #[test]
    fn visual_state_styles_remain_application_owned() {
        let _ = Link::new("states")
            .styles(|styles| styles.disabled(|style| style.opacity(0.5)))
            .hover(|style| style.opacity(0.9))
            .active(|style| style.opacity(0.8))
            .focus_visible(|style| style.opacity(0.7));
    }

    #[test]
    fn disabled_style_applies_only_while_disabled_and_then_wins() {
        let enabled = Link::new("enabled")
            .opacity(0.9)
            .styles(|styles| styles.disabled(|style| style.opacity(0.5)));
        assert_eq!(enabled.resolved_style().opacity, Some(0.9));

        let disabled = Link::new("disabled")
            .styles(|styles| styles.disabled(|style| style.opacity(0.5)))
            .opacity(0.9)
            .disabled(true);
        assert_eq!(disabled.resolved_style().opacity, Some(0.5));

        let semantic_only = Link::new("semantic-only")
            .styles(|styles| styles.disabled(|style| style.opacity(0.5)))
            .disabled(true);
        assert_eq!(semantic_only.resolved_style().opacity, Some(0.5));
    }

    #[gpui::test]
    fn accessibility_exposes_link_role_label_and_action_surface(cx: &mut TestAppContext) {
        type Captured = Arc<Mutex<Option<(accesskit::Node, accesskit::Node)>>>;

        struct A11yProbe {
            captured: Captured,
        }

        impl Render for A11yProbe {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let captured = self.captured.clone();
                canvas(
                    move |_, window, cx| {
                        let mut info = |link: Link| {
                            let mut node = accesskit::Node::new(Role::Link);
                            link.render(window, cx)
                                .into_element()
                                .write_a11y_info(&mut node);
                            node
                        };
                        let enabled = info(
                            Link::new("enabled")
                                .href("app://settings")
                                .accessibility_label("Settings")
                                .open_with(|_, _, _, _| {}),
                        );
                        let disabled = info(
                            Link::new("disabled")
                                .disabled(true)
                                .accessibility_label("Settings")
                                .on_activate(|_, _, _| {}),
                        );
                        *captured.lock().unwrap() = Some((enabled, disabled));
                    },
                    |_, _, _, _| {},
                )
            }
        }

        let captured: Captured = Arc::new(Mutex::new(None));
        let result = captured.clone();
        let (_, cx) = cx.add_window_view(move |_, _| A11yProbe { captured });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let (enabled, disabled) = result.lock().unwrap().take().unwrap();

        assert_eq!(enabled.role(), Role::Link);
        assert_eq!(enabled.label(), Some("Settings"));
        assert!(enabled.supports_action(accesskit::Action::Click));
        assert_eq!(enabled.url(), None);

        assert_eq!(disabled.role(), Role::Link);
        assert!(!disabled.supports_action(accesskit::Action::Click));
        assert!(!enabled.is_disabled());
        assert!(disabled.is_disabled());
    }
}
