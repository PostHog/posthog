use std::{rc::Rc, time::Duration};

use gpui::{
    AnyElement, AnyView, App, Context, Div, ElementId, Entity, EventEmitter,
    InteractiveElement as _, IntoElement, ParentElement as _, RenderOnce, StyleRefinement, Styled,
    Window, div, prelude::FluentBuilder as _,
};

use crate::{
    History, StyledExt as _,
    motion::{Presence, PresencePhase, Transition},
};

/// What a running transition is doing, in Qt's terms.
///
/// The operation decides paint order and lets a renderer move a pushed view
/// differently from a popped one.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NavOperation {
    /// A view was pushed over the previous top.
    Push,
    /// The top was popped, revealing the view below.
    Pop,
    /// The top was swapped for another view.
    Replace,
}

/// Whether one change runs the [`NavStack`]'s transition, as UIKit's
/// `animated:` and Qt's `StackView.Immediate` decide per call.
///
/// `Immediate` switches views on the spot even when the element has a
/// transition, which is what restoring a stack at launch or jumping to a
/// page from a command wants. A `NavStack` without a transition is always
/// immediate, whatever is passed here.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NavMotion {
    Animated,
    Immediate,
}

/// Emitted by [`NavStackState`] after the stack changed.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NavStackEvent {
    Pushed,
    Popped,
    Forwarded,
    Replaced,
    Cleared,
}

/// The view leaving the stack, kept mounted until its exit transition
/// finishes. The element samples that transition as a [`Presence`] keyed by
/// the view, so an interrupted change reverses from where it is.
#[derive(Clone)]
struct Transit {
    outgoing: AnyView,
    /// The position the outgoing view had on the stack.
    index: usize,
    operation: NavOperation,
    motion: NavMotion,
}

/// A stack of views, one visible at a time, with the pages popped off it
/// kept for `forward`.
///
/// This is SwiftUI's `NavigationStack`, Qt's `StackView` and WinUI's
/// `Frame`: navigation between pages. Underneath it is a [`History`] of
/// views from the root through the current page. A popped page becomes a
/// forward entry until a push discards that forward branch, which is what
/// WinUI's `BackStack` and `ForwardStack` do.
///
/// The stack owns which view is current and the lifecycle of a change: after
/// a push, pop or replace, the outgoing view stays mounted until the
/// [`NavStack`]'s transition finishes, so the application can animate it.
/// The views themselves, and what a transition looks like, belong to the
/// application.
///
/// `pop` keeps the root, as Qt's `StackView` and UIKit's navigation controller
/// do; `clear` is the way to empty the stack. A back button is shown when
/// `depth() > 1`, a forward button when `forward_views()` is not empty.
pub struct NavStackState {
    history: History<NavEntry>,
    transit: Option<Transit>,
}

/// A view on the stack. A page pushed twice is two separate entries.
#[derive(Clone)]
struct NavEntry {
    view: AnyView,
}

impl NavEntry {
    fn new(view: impl Into<AnyView>) -> Self {
        Self { view: view.into() }
    }
}

impl EventEmitter<NavStackEvent> for NavStackState {}

impl Default for NavStackState {
    fn default() -> Self {
        Self::new()
    }
}

impl NavStackState {
    pub fn new() -> Self {
        Self {
            history: History::new(),
            transit: None,
        }
    }

    /// The number of views on the stack.
    pub fn depth(&self) -> usize {
        self.history.entries().len()
    }

    pub fn is_empty(&self) -> bool {
        self.history.entries().len() == 0
    }

    /// The view on top of the stack, which is the one shown once any
    /// transition has finished.
    pub fn current(&self) -> Option<&AnyView> {
        self.history.current().map(|entry| &entry.view)
    }

    /// Every view on the stack, root first.
    pub fn views(&self) -> impl ExactSizeIterator<Item = &AnyView> {
        self.history.entries().map(|entry| &entry.view)
    }

    /// The views popped since the last push, nearest first: the one
    /// `forward` would bring back is the first.
    pub fn forward_views(&self) -> impl ExactSizeIterator<Item = &AnyView> {
        self.history.forward_entries().map(|entry| &entry.view)
    }

    /// Pushes `view` on top of the stack and discards the forward views.
    ///
    /// Into an empty stack this is immediate, like Qt's `initialItem`. Over
    /// an existing top it starts a [`NavOperation::Push`] transition, unless
    /// `motion` is [`NavMotion::Immediate`].
    pub fn push(&mut self, view: impl Into<AnyView>, motion: NavMotion, cx: &mut Context<Self>) {
        let outgoing = self.top();
        self.history.push(NavEntry::new(view));
        self.finish(
            outgoing,
            NavOperation::Push,
            motion,
            NavStackEvent::Pushed,
            cx,
        );
    }

    /// Pops the top view and returns it, starting a [`NavOperation::Pop`]
    /// transition to the view below. The view waits in `forward_views`.
    ///
    /// The root is never popped: this returns `None` at a depth of one or
    /// less.
    pub fn pop(&mut self, motion: NavMotion, cx: &mut Context<Self>) -> Option<AnyView> {
        if self.depth() <= 1 {
            return None;
        }
        let popped = self.top()?;
        self.history.back()?;
        self.finish(
            Some(popped.clone()),
            NavOperation::Pop,
            motion,
            NavStackEvent::Popped,
            cx,
        );
        Some(popped.0)
    }

    /// Pops every view above the root in one [`NavOperation::Pop`]
    /// transition from the previous top, and returns them root-side first.
    pub fn pop_to_root(&mut self, motion: NavMotion, cx: &mut Context<Self>) -> Vec<AnyView> {
        let outgoing = self.top();
        let mut popped = Vec::new();
        while self.depth() > 1 {
            let Some(view) = self.current().cloned() else {
                break;
            };
            if self.history.back().is_none() {
                break;
            }
            popped.push(view);
        }
        if popped.is_empty() {
            return popped;
        }
        self.finish(
            outgoing,
            NavOperation::Pop,
            motion,
            NavStackEvent::Popped,
            cx,
        );
        popped.reverse();
        popped
    }

    /// Brings back the most recently popped view, starting a
    /// [`NavOperation::Push`] transition over the current top, and returns
    /// it. `None` when nothing has been popped since the last push.
    pub fn forward(&mut self, motion: NavMotion, cx: &mut Context<Self>) -> Option<AnyView> {
        let outgoing = self.top();
        let view = self.history.forward()?.view;
        self.finish(
            outgoing,
            NavOperation::Push,
            motion,
            NavStackEvent::Forwarded,
            cx,
        );
        Some(view)
    }

    /// Swaps the top view for `view` and returns the one replaced, starting a
    /// [`NavOperation::Replace`] transition. The forward views are kept. On
    /// an empty stack this is a push.
    pub fn replace(
        &mut self,
        view: impl Into<AnyView>,
        motion: NavMotion,
        cx: &mut Context<Self>,
    ) -> Option<AnyView> {
        let Some(replaced) = self.top() else {
            self.push(view, motion, cx);
            return None;
        };
        self.history.replace_current(NavEntry::new(view));
        self.finish(
            Some(replaced.clone()),
            NavOperation::Replace,
            motion,
            NavStackEvent::Replaced,
            cx,
        );
        Some(replaced.0)
    }

    /// Empties the stack and the forward views immediately, abandoning any
    /// running transition.
    pub fn clear(&mut self, cx: &mut Context<Self>) {
        self.history.clear();
        self.transit = None;
        cx.emit(NavStackEvent::Cleared);
        cx.notify();
    }

    /// The top view with its position, before an operation moves it.
    fn top(&self) -> Option<(AnyView, usize)> {
        let index = self.depth().checked_sub(1)?;
        self.current().cloned().map(|view| (view, index))
    }

    /// Records the change: `outgoing` stays mounted until its exit
    /// transition finishes, or not at all for an immediate change. A change
    /// already in transit is superseded, so at most one outgoing view is ever
    /// mounted; the element reverses its presence from wherever it is.
    fn finish(
        &mut self,
        outgoing: Option<(AnyView, usize)>,
        operation: NavOperation,
        motion: NavMotion,
        event: NavStackEvent,
        cx: &mut Context<Self>,
    ) {
        self.transit = outgoing.map(|(outgoing, index)| Transit {
            outgoing,
            index,
            operation,
            motion,
        });
        cx.emit(event);
        cx.notify();
    }
}

type ItemRenderer = Rc<dyn Fn(NavPage, &mut Window, &mut App) -> AnyElement>;

/// An unstyled host for a [`NavStackState`].
///
/// The container is positioned so that the two views of a transition can
/// overlap; each mounted view is handed to the `item` renderer as a
/// [`NavPage`] that already fills the container. Everything else — size,
/// clipping, background, and how a transition moves — is the application's.
///
/// Without a `transition` the stack switches views immediately, as it also
/// does under reduced motion.
#[derive(IntoElement)]
pub struct NavStack {
    base: Div,
    style: StyleRefinement,
    state: Entity<NavStackState>,
    transition: Option<Transition>,
    render_item: Option<ItemRenderer>,
}

impl NavStack {
    pub fn new(state: &Entity<NavStackState>) -> Self {
        Self {
            base: div(),
            style: StyleRefinement::default(),
            state: state.clone(),
            transition: None,
            render_item: None,
        }
    }

    /// The timing every push, pop and replace runs under.
    pub fn transition(mut self, transition: Transition) -> Self {
        self.transition = Some(transition);
        self
    }

    /// Renders each mounted view. The item is already positioned to fill the
    /// container; refine it to move or fade the view by its phase and
    /// progress, then return it.
    pub fn item(
        mut self,
        render: impl Fn(NavPage, &mut Window, &mut App) -> AnyElement + 'static,
    ) -> Self {
        self.render_item = Some(Rc::new(render));
        self
    }
}

impl Styled for NavStack {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for NavStack {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let (current, depth, transit) = {
            let state = self.state.read(cx);
            (
                state.current().cloned(),
                state.depth(),
                state.transit.clone(),
            )
        };
        let immediate = cx.reduce_motion()
            || self.transition.is_none()
            || transit
                .as_ref()
                .is_some_and(|transit| transit.motion == NavMotion::Immediate);
        let transition = if immediate {
            Transition::new(Duration::ZERO)
        } else {
            self.transition
                .clone()
                .unwrap_or_else(|| Transition::new(Duration::ZERO))
        };

        // The outgoing view's presence is the change's clock: its exit runs
        // 1 → 0, reversing if the change is interrupted, and both pages of
        // the change read their progress from it.
        let change = transit.and_then(|transit| {
            let sample = Presence::new(page_id(&transit.outgoing), false)
                .transition(transition.clone())
                .sample(window, cx);
            if sample.should_render() {
                Some((transit, 1.0 - sample.progress))
            } else {
                self.state.update(cx, |state, _| state.transit = None);
                None
            }
        });

        // The current view's presence is sampled too, so a view brought back
        // by `forward` or revealed by `pop` starts its next exit from present.
        // With nothing changing it settles on the spot; the root does not
        // animate in.
        if let Some(current) = &current {
            let transition = if change.is_some() {
                transition
            } else {
                Transition::new(Duration::ZERO)
            };
            Presence::new(page_id(current), true)
                .transition(transition)
                .sample(window, cx);
        }

        let mut items = Vec::with_capacity(3);
        if let Some(current) = current {
            let index = depth - 1;
            match change {
                Some((transit, progress)) => {
                    let current = NavPage::new(
                        current,
                        index,
                        PresencePhase::Entering,
                        Some(transit.operation),
                        progress,
                    );
                    let outgoing = NavPage::new(
                        transit.outgoing,
                        transit.index,
                        PresencePhase::Exiting,
                        Some(transit.operation),
                        progress,
                    );
                    // A pushed or replacing view paints over what it covers; a
                    // popped view paints over what it reveals.
                    match transit.operation {
                        NavOperation::Push | NavOperation::Replace => {
                            items.push(outgoing);
                            items.push(current);
                        }
                        NavOperation::Pop => {
                            items.push(current);
                            items.push(outgoing);
                        }
                    }
                }
                None => items.push(NavPage::new(
                    current,
                    index,
                    PresencePhase::Present,
                    None,
                    1.0,
                )),
            }
        }
        let changing = items.len() > 1;

        let render_item = self.render_item;
        self.base
            .relative()
            .refine_style(&self.style)
            .children(items.into_iter().map(|item| match &render_item {
                Some(render) => render(item, window, cx),
                None => item.into_any_element(),
            }))
            // Neither page takes pointer input while the change runs: the
            // outgoing one is on its way out, and the incoming one is not yet
            // where it will be.
            .when(changing, |this| {
                this.child(div().absolute().inset_0().occlude())
            })
    }
}

fn page_id(view: &AnyView) -> ElementId {
    ("nav-stack", view.entity_id()).into()
}

/// One mounted view of a [`NavStack`], handed to the item renderer.
///
/// The item fills its container. Its readers describe where the view is in
/// the change that is running, so the renderer can move it: `phase` says
/// whether it is arriving, settled, or leaving; `operation` says which
/// change; `progress` runs from `0.0` to `1.0` over the transition, already
/// eased, and is shared by both views of one change.
#[derive(IntoElement)]
pub struct NavPage {
    base: Div,
    style: StyleRefinement,
    view: AnyView,
    index: usize,
    phase: PresencePhase,
    operation: Option<NavOperation>,
    progress: f32,
}

impl NavPage {
    fn new(
        view: AnyView,
        index: usize,
        phase: PresencePhase,
        operation: Option<NavOperation>,
        progress: f32,
    ) -> Self {
        Self {
            base: div(),
            style: StyleRefinement::default(),
            view,
            index,
            phase,
            operation,
            progress,
        }
    }

    pub fn view(&self) -> &AnyView {
        &self.view
    }

    /// The view's position on the stack, root first. A view on its way out
    /// keeps the position it had.
    pub fn index(&self) -> usize {
        self.index
    }

    pub fn phase(&self) -> PresencePhase {
        self.phase
    }

    /// The change in progress, or `None` once the stack has settled.
    pub fn operation(&self) -> Option<NavOperation> {
        self.operation
    }

    pub fn progress(&self) -> f32 {
        self.progress
    }
}

impl Styled for NavPage {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for NavPage {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        self.base
            .absolute()
            .inset_0()
            .child(self.view)
            .refine_style(&self.style)
    }
}

#[cfg(test)]
mod tests {
    use std::{cell::RefCell, time::Duration};

    use gpui::{AppContext as _, Render, TestAppContext};

    use super::*;

    struct Page;

    impl Render for Page {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
        }
    }

    fn page(cx: &mut TestAppContext) -> AnyView {
        cx.new(|_| Page).into()
    }

    fn stack(cx: &mut TestAppContext) -> (Entity<NavStackState>, Rc<RefCell<Vec<NavStackEvent>>>) {
        let stack = cx.new(|_| NavStackState::new());
        let events = Rc::new(RefCell::new(Vec::new()));
        cx.update({
            let events = events.clone();
            let stack = stack.clone();
            move |cx| {
                cx.subscribe(&stack, move |_, event: &NavStackEvent, _| {
                    events.borrow_mut().push(*event);
                })
                .detach();
            }
        });
        (stack, events)
    }

    #[gpui::test]
    fn push_and_pop_keep_the_root(cx: &mut TestAppContext) {
        let (stack, events) = stack(cx);
        let (root, second) = (page(cx), page(cx));

        stack.update(cx, |stack, cx| {
            stack.push(root.clone(), NavMotion::Animated, cx)
        });
        assert!(stack.read_with(cx, |stack, _| stack.transit.is_none()));

        stack.update(cx, |stack, cx| {
            stack.push(second.clone(), NavMotion::Animated, cx)
        });
        stack.read_with(cx, |stack, _| {
            assert_eq!(stack.depth(), 2);
            assert_eq!(stack.current(), Some(&second));
            let transit = stack
                .transit
                .as_ref()
                .expect("push over a view transitions");
            assert_eq!(transit.operation, NavOperation::Push);
            assert_eq!(transit.outgoing, root);
        });

        let popped = stack.update(cx, |stack, cx| stack.pop(NavMotion::Animated, cx));
        assert_eq!(popped, Some(second.clone()));
        stack.read_with(cx, |stack, _| {
            assert_eq!(stack.views().collect::<Vec<_>>(), [&root]);
            let transit = stack.transit.as_ref().expect("pop transitions");
            assert_eq!(transit.operation, NavOperation::Pop);
            assert_eq!(transit.outgoing, second);
            assert_eq!(transit.index, 1, "the popped view keeps its position");
        });

        assert_eq!(
            stack.update(cx, |stack, cx| stack.pop(NavMotion::Animated, cx)),
            None
        );
        assert_eq!(stack.read_with(cx, |stack, _| stack.depth()), 1);
        assert_eq!(
            &*events.borrow(),
            &[
                NavStackEvent::Pushed,
                NavStackEvent::Pushed,
                NavStackEvent::Popped
            ]
        );
    }

    #[gpui::test]
    fn pop_to_root_returns_everything_above_it(cx: &mut TestAppContext) {
        let (stack, _) = stack(cx);
        let pages: Vec<AnyView> = (0..3).map(|_| page(cx)).collect();
        for view in &pages {
            stack.update(cx, |stack, cx| {
                stack.push(view.clone(), NavMotion::Animated, cx)
            });
        }

        assert_eq!(
            stack.update(cx, |stack, cx| stack.pop_to_root(NavMotion::Animated, cx)),
            pages[1..]
        );
        stack.read_with(cx, |stack, _| {
            assert_eq!(stack.views().cloned().collect::<Vec<_>>(), pages[..1]);
            let transit = stack.transit.as_ref().expect("pop_to_root transitions");
            assert_eq!(transit.outgoing, pages[2]);
            assert_eq!(transit.index, 2, "the previous top keeps its position");
        });
        assert!(
            stack
                .update(cx, |stack, cx| stack.pop_to_root(NavMotion::Animated, cx))
                .is_empty()
        );
    }

    #[gpui::test]
    fn replace_swaps_the_top_and_pushes_into_an_empty_stack(cx: &mut TestAppContext) {
        let (stack, events) = stack(cx);
        let (first, second) = (page(cx), page(cx));

        assert_eq!(
            stack.update(cx, |stack, cx| stack.replace(
                first.clone(),
                NavMotion::Animated,
                cx
            )),
            None
        );
        assert_eq!(
            stack.update(cx, |stack, cx| stack.replace(
                second.clone(),
                NavMotion::Animated,
                cx
            )),
            Some(first.clone())
        );
        stack.read_with(cx, |stack, _| {
            assert_eq!(stack.views().collect::<Vec<_>>(), [&second]);
            let transit = stack.transit.as_ref().expect("replace transitions");
            assert_eq!(transit.operation, NavOperation::Replace);
            assert_eq!(transit.outgoing, first);
            assert_eq!(
                transit.index, 0,
                "the replaced view sat where the new one sits"
            );
        });

        stack.update(cx, |stack, cx| stack.clear(cx));
        stack.read_with(cx, |stack, _| {
            assert!(stack.is_empty());
            assert!(stack.transit.is_none());
        });
        assert_eq!(
            &*events.borrow(),
            &[
                NavStackEvent::Pushed,
                NavStackEvent::Replaced,
                NavStackEvent::Cleared
            ]
        );
    }

    #[gpui::test]
    fn popped_views_wait_for_forward_until_the_next_push(cx: &mut TestAppContext) {
        let (stack, events) = stack(cx);
        let pages: Vec<AnyView> = (0..3).map(|_| page(cx)).collect();
        for view in &pages {
            stack.update(cx, |stack, cx| {
                stack.push(view.clone(), NavMotion::Animated, cx)
            });
        }
        assert!(
            stack
                .update(cx, |stack, cx| stack.forward(NavMotion::Animated, cx))
                .is_none()
        );

        stack.update(cx, |stack, cx| {
            stack.pop(NavMotion::Animated, cx);
            stack.pop(NavMotion::Animated, cx);
        });
        stack.read_with(cx, |stack, _| {
            assert_eq!(stack.depth(), 1);
            assert_eq!(
                stack.forward_views().cloned().collect::<Vec<_>>(),
                pages[1..]
            );
        });

        let brought_back = stack.update(cx, |stack, cx| stack.forward(NavMotion::Animated, cx));
        assert_eq!(brought_back, Some(pages[1].clone()));
        stack.read_with(cx, |stack, _| {
            assert_eq!(stack.current(), Some(&pages[1]));
            let transit = stack
                .transit
                .as_ref()
                .expect("forward transitions like a push");
            assert_eq!(transit.operation, NavOperation::Push);
            assert_eq!(transit.outgoing, pages[0]);
            assert_eq!(stack.forward_views().len(), 1);
        });

        let fresh = page(cx);
        stack.update(cx, |stack, cx| stack.push(fresh, NavMotion::Animated, cx));
        assert_eq!(
            stack.read_with(cx, |stack, _| stack.forward_views().len()),
            0
        );
        assert_eq!(events.borrow().last(), Some(&NavStackEvent::Pushed));
        assert!(events.borrow().contains(&NavStackEvent::Forwarded));
    }

    #[gpui::test]
    fn an_immediate_change_records_its_motion_and_supersedes_the_running_one(
        cx: &mut TestAppContext,
    ) {
        let (stack, events) = stack(cx);
        let (root, second, third) = (page(cx), page(cx), page(cx));
        stack.update(cx, |stack, cx| {
            stack.push(root, NavMotion::Animated, cx);
            stack.push(second.clone(), NavMotion::Animated, cx);
            stack.push(third.clone(), NavMotion::Immediate, cx);
        });
        stack.read_with(cx, |stack, _| {
            assert_eq!(stack.current(), Some(&third));
            let transit = stack.transit.as_ref().expect("the change is recorded");
            assert_eq!(transit.motion, NavMotion::Immediate);
            assert_eq!(transit.outgoing, second, "the running push was superseded");
        });
        assert_eq!(
            stack.update(cx, |stack, cx| stack.pop(NavMotion::Immediate, cx)),
            Some(third.clone())
        );
        stack.read_with(cx, |stack, _| {
            let transit = stack.transit.as_ref().unwrap();
            assert_eq!(transit.motion, NavMotion::Immediate);
            assert_eq!(transit.outgoing, third);
        });
        assert_eq!(events.borrow().len(), 4);
    }

    struct Host {
        stack: Entity<NavStackState>,
    }

    impl Render for Host {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            NavStack::new(&self.stack)
                .size_full()
                .transition(Transition::new(Duration::from_millis(200)))
        }
    }

    #[gpui::test]
    fn the_outgoing_view_is_dropped_once_its_exit_has_run(cx: &mut TestAppContext) {
        let stack = cx.new(|_| NavStackState::new());
        let (root, second) = (page(cx), page(cx));
        let (_, cx) = cx.add_window_view({
            let stack = stack.clone();
            move |_, _| Host { stack }
        });
        stack.update(cx, |stack, cx| {
            stack.push(root, NavMotion::Immediate, cx);
            stack.push(second, NavMotion::Animated, cx);
        });

        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(stack.read_with(cx, |stack, _| stack.transit.is_some()));

        cx.executor().advance_clock(Duration::from_millis(100));
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(stack.read_with(cx, |stack, _| stack.transit.is_some()));

        cx.executor().advance_clock(Duration::from_millis(150));
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(stack.read_with(cx, |stack, _| stack.transit.is_none()));

        // An immediate change is gone after the frame that draws it.
        stack.update(cx, |stack, cx| {
            stack.pop(NavMotion::Immediate, cx);
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        assert!(stack.read_with(cx, |stack, _| stack.transit.is_none()));
    }

    #[gpui::test]
    fn a_new_operation_replaces_the_running_transition(cx: &mut TestAppContext) {
        let (stack, _) = stack(cx);
        let pages: Vec<AnyView> = (0..3).map(|_| page(cx)).collect();
        for view in &pages {
            stack.update(cx, |stack, cx| {
                stack.push(view.clone(), NavMotion::Animated, cx)
            });
        }
        stack.update(cx, |stack, cx| {
            stack.pop(NavMotion::Animated, cx);
        });
        stack.read_with(cx, |stack, _| {
            let transit = stack.transit.as_ref().unwrap();
            assert_eq!(transit.operation, NavOperation::Pop);
            assert_eq!(transit.outgoing, pages[2]);
        });
    }
}
