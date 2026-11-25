#[cfg(not(target_family = "wasm"))]
use std::time::Instant;
use std::{
    cell::RefCell,
    rc::{Rc, Weak},
};
#[cfg(target_family = "wasm")]
use web_time::Instant;

use gpui::{App, Bounds, Entity, Global, OwnedMenu, Pixels, Point};

use crate::text::TextViewState;

/// Holds the deferred interaction context open for as long as it is alive.
///
/// Handed out by [`GlobalState::register_deferred_popover`]; drop it to close
/// the context again. The registry only ever weighs the token's liveness, so
/// there is nothing inside to read.
pub struct DeferredPopover(#[allow(dead_code)] Rc<()>);

/// Application-wide state shared by Base behaviors.
pub struct GlobalState {
    app_menus: Vec<OwnedMenu>,
    deferred_popovers: Vec<Weak<()>>,
    suppress_text_selection: bool,
    /// The text views being prepainted or painted, innermost last. Kept
    /// apart from what views read of this global: pushing and popping as
    /// they draw is not a change of it.
    text_view_state_stack: RefCell<Vec<Entity<TextViewState>>>,
    /// The table cells being prepainted or painted, innermost last.
    table_cell_stack: RefCell<Vec<Bounds<Pixels>>>,
    /// When a finger last went down. A tap reaches controls as a mouse press;
    /// this is how they tell it from one.
    last_touch: Option<Instant>,
}

impl Global for GlobalState {}

impl GlobalState {
    fn new() -> Self {
        Self {
            app_menus: Vec::new(),
            deferred_popovers: Vec::new(),
            suppress_text_selection: false,
            text_view_state_stack: RefCell::new(Vec::new()),
            table_cell_stack: RefCell::new(Vec::new()),
            last_touch: None,
        }
    }

    /// Records that a finger went down. Called from the touch drag GPUI
    /// offers on every touch, before it becomes a tap, a long press or a pan.
    pub fn note_touch(cx: &mut App) {
        Self::init(cx);
        Self::global_mut(cx).last_touch = Some(Instant::now());
    }

    /// Whether the press being handled came from a finger: a touch went
    /// down recently enough that the mouse events of a tap are still
    /// arriving. A double tap takes up to twice the tap interval.
    pub fn is_touch_press(cx: &App) -> bool {
        cx.try_global::<Self>()
            .and_then(|state| state.last_touch)
            .is_some_and(|at| at.elapsed() < std::time::Duration::from_secs(1))
    }

    /// Ensures that the Base global exists.
    #[doc(hidden)]
    pub fn init(cx: &mut App) {
        if !cx.has_global::<Self>() {
            cx.set_global(Self::new());
        }
    }

    /// Suppresses window-level text selection for the current mouse down.
    ///
    /// Controls that own a press or drag interaction use this so the same
    /// pointer event does not also start application text selection.
    pub fn suppress_text_selection(cx: &mut App) {
        Self::global_mut(cx).suppress_text_selection = true;
    }

    /// Clears the current mouse-down text-selection suppression.
    #[doc(hidden)]
    pub fn reset_text_selection_suppression(cx: &mut App) {
        Self::global_mut(cx).suppress_text_selection = false;
    }

    /// Returns whether the current mouse down suppresses text selection.
    #[doc(hidden)]
    pub fn is_text_selection_suppressed(cx: &App) -> bool {
        Self::global(cx).suppress_text_selection
    }

    pub fn global(cx: &App) -> &Self {
        cx.global::<Self>()
    }

    pub fn global_mut(cx: &mut App) -> &mut Self {
        cx.global_mut::<Self>()
    }

    pub(crate) fn text_view_state(&self) -> Option<Entity<TextViewState>> {
        self.text_view_state_stack.borrow().last().cloned()
    }

    pub(crate) fn push_text_view_state(&self, state: Entity<TextViewState>) {
        self.text_view_state_stack.borrow_mut().push(state);
    }

    pub(crate) fn pop_text_view_state(&self) {
        self.text_view_state_stack.borrow_mut().pop();
    }

    /// Enters the table cell being prepainted or painted.
    pub(crate) fn push_table_cell(&self, bounds: Bounds<Pixels>) {
        self.table_cell_stack.borrow_mut().push(bounds);
    }

    pub(crate) fn pop_table_cell(&self) {
        self.table_cell_stack.borrow_mut().pop();
    }

    /// The table cell being prepainted or painted, if any.
    pub(crate) fn table_cell(&self) -> Option<Bounds<Pixels>> {
        self.table_cell_stack.borrow().last().copied()
    }

    #[doc(hidden)]
    // Kept for compatibility; automatic order now belongs to the window's selection state.
    pub fn begin_selection_frame(&self) {}

    /// Returns the application menus.
    pub fn app_menus(&self) -> &[OwnedMenu] {
        &self.app_menus
    }

    /// Replaces the application menus.
    pub fn set_app_menus(&mut self, menus: Vec<OwnedMenu>) {
        self.app_menus = menus;
    }

    /// Returns whether any deferred popup currently owns an open interaction
    /// context.
    pub fn is_in_deferred_context(cx: &App) -> bool {
        Self::global(cx)
            .deferred_popovers
            .iter()
            .any(|popover| popover.strong_count() > 0)
    }

    /// Registers an open deferred popup, which stays registered for as long as
    /// the returned token is held.
    ///
    /// A token rather than an identifier, because popup state is routinely
    /// dropped without ever being closed: state that stops being rendered — a
    /// popover scrolled out of a virtual list, a panel closed while its menu is
    /// open — is collected at the end of the frame, with no chance to
    /// deregister. A registration that outlived its popup would leave the
    /// application believing a popup is open forever, and everything that
    /// steps aside for open popups (the native context menu of a text input,
    /// say) would stay disabled for the rest of the session.
    pub fn register_deferred_popover(cx: &mut App) -> DeferredPopover {
        let token = Rc::new(());
        let state = Self::global_mut(cx);
        state
            .deferred_popovers
            .retain(|popover| popover.strong_count() > 0);
        state.deferred_popovers.push(Rc::downgrade(&token));
        DeferredPopover(token)
    }
}

/// Confines a selection to its anchor cell and excludes text in other cells.
pub(crate) fn confine_to_cell(
    anchor_cell: Option<(Point<Pixels>, Bounds<Pixels>)>,
    painting: Option<Bounds<Pixels>>,
    anchor: Point<Pixels>,
    cursor: Point<Pixels>,
) -> Option<(Point<Pixels>, Point<Pixels>)> {
    let Some((_, cell)) = anchor_cell.filter(|(cell_anchor, _)| *cell_anchor == anchor) else {
        return Some((anchor, cursor));
    };
    if painting != Some(cell) {
        return None;
    }
    let cursor = gpui::point(
        cursor.x.clamp(cell.left(), cell.right()),
        cursor.y.clamp(cell.top(), cell.bottom()),
    );
    Some((anchor, cursor))
}

#[cfg(test)]
mod tests {
    use super::*;

    mod table_cell {
        use gpui::{Bounds, point, px, size};

        use super::super::confine_to_cell;

        fn cell(x: f32) -> Bounds<gpui::Pixels> {
            Bounds::new(point(px(x), px(0.)), size(px(100.), px(30.)))
        }

        #[test]
        fn a_drag_outside_a_cell_is_unchanged() {
            let (anchor, cursor) = (point(px(5.), px(5.)), point(px(250.), px(80.)));
            assert_eq!(
                confine_to_cell(None, Some(cell(0.)), anchor, cursor),
                Some((anchor, cursor))
            );
            // A cell from an older drag does not hold this anchor.
            let old = Some((point(px(50.), px(10.)), cell(0.)));
            assert_eq!(
                confine_to_cell(old, None, anchor, cursor),
                Some((anchor, cursor))
            );
        }

        #[test]
        fn a_drag_from_a_cell_selects_nothing_outside_it() {
            let anchor = point(px(10.), px(10.));
            let anchor_cell = Some((anchor, cell(0.)));
            let cursor = point(px(150.), px(20.));
            assert_eq!(
                confine_to_cell(anchor_cell, Some(cell(100.)), anchor, cursor),
                None
            );
            assert_eq!(confine_to_cell(anchor_cell, None, anchor, cursor), None);
        }

        #[test]
        fn a_drag_from_a_cell_is_clamped_to_it() {
            let anchor = point(px(10.), px(10.));
            let anchor_cell = Some((anchor, cell(0.)));
            assert_eq!(
                confine_to_cell(
                    anchor_cell,
                    Some(cell(0.)),
                    anchor,
                    point(px(250.), px(80.))
                ),
                Some((anchor, point(px(100.), px(30.))))
            );
            assert_eq!(
                confine_to_cell(
                    anchor_cell,
                    Some(cell(0.)),
                    anchor,
                    point(px(-20.), px(-5.))
                ),
                Some((anchor, point(px(0.), px(0.))))
            );
            let inside = point(px(60.), px(12.));
            assert_eq!(
                confine_to_cell(anchor_cell, Some(cell(0.)), anchor, inside),
                Some((anchor, inside))
            );
        }
    }

    #[gpui::test]
    fn initialization_is_idempotent_and_suppression_can_be_reset(cx: &mut gpui::TestAppContext) {
        cx.update(|cx| {
            GlobalState::init(cx);
            GlobalState::suppress_text_selection(cx);
            GlobalState::init(cx);
            assert!(GlobalState::is_text_selection_suppressed(cx));

            GlobalState::reset_text_selection_suppression(cx);
            assert!(!GlobalState::is_text_selection_suppressed(cx));

            assert!(!GlobalState::is_in_deferred_context(cx));
            let popover = GlobalState::register_deferred_popover(cx);
            assert!(GlobalState::is_in_deferred_context(cx));
            drop(popover);
            assert!(!GlobalState::is_in_deferred_context(cx));
        });
    }

    /// Popup state is routinely dropped without being closed first, and a
    /// registration that survived it would disable everything that steps aside
    /// for an open popup, permanently.
    #[gpui::test]
    fn a_dropped_registration_closes_the_deferred_context(cx: &mut gpui::TestAppContext) {
        cx.update(|cx| {
            GlobalState::init(cx);

            let outer = GlobalState::register_deferred_popover(cx);
            {
                let _inner = GlobalState::register_deferred_popover(cx);
                assert!(GlobalState::is_in_deferred_context(cx));
            }
            assert!(GlobalState::is_in_deferred_context(cx));

            drop(outer);
            assert!(!GlobalState::is_in_deferred_context(cx));

            // Registering again must not resurrect the collected ones.
            let popover = GlobalState::register_deferred_popover(cx);
            assert_eq!(GlobalState::global(cx).deferred_popovers.len(), 1);
            drop(popover);
            assert!(!GlobalState::is_in_deferred_context(cx));
        });
    }
}
