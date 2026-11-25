//! The presentation half of a dockable panel, and the concrete handle that
//! carries it back across the renderer seam.
//!
//! `gpui-base` owns panel *behavior*: [`gpui_base::dock::Panel`] and its
//! object-safe mirror answer for the name, the id, closability, visibility,
//! and the activation callbacks. Everything a tab bar actually draws — the
//! title, the tab name, the toolbar, the ellipsis menu — is presentation and
//! lives here.
//!
//! A sub-trait alone cannot join the two. Base hands a skin
//! `Arc<dyn gpui_base::dock::PanelView>`; `Arc<dyn PanelView>` coerces *to*
//! that, and Rust has no coercion back, so a renderer holding base's handle
//! can never reach a presentation method through it. What does work is a
//! *concrete* type: [`PanelHandle`] wraps `Arc<dyn PanelView>` and implements
//! base's trait by delegation, so base holds a `PanelHandle` and the skin
//! recovers it with [`PanelHandle::of`], which downcasts to a single known
//! type.

use std::{any::Any, sync::Arc};

use gpui::{
    AnyElement, AnyView, App, Context, Entity, FocusHandle, Hsla, IntoElement, SharedString,
    WeakEntity, Window,
};
use gpui_base::dock::{PanelId, PanelState, TabGroup};
use rust_i18n::t;

use crate::{button::Button, menu::PopupMenu};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum PanelStyle {
    /// Display the TabBar when there are multiple tabs, otherwise display the simple title.
    #[default]
    Auto,
    /// Always display the tab bar.
    TabBar,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TitleStyle {
    pub background: Hsla,
    pub foreground: Hsla,
}

#[derive(Clone, Copy, Default)]
pub enum PanelControl {
    Both,
    #[default]
    Menu,
    Toolbar,
}

impl PanelControl {
    #[inline]
    pub fn toolbar_visible(&self) -> bool {
        matches!(self, PanelControl::Both | PanelControl::Toolbar)
    }

    #[inline]
    pub fn menu_visible(&self) -> bool {
        matches!(self, PanelControl::Both | PanelControl::Menu)
    }
}

/// What a panel draws, on top of the behavior [`gpui_base::dock::Panel`]
/// defines.
///
/// Everything here has a default, so a panel that only implements base's trait
/// plus this one gets an unnamed title and no chrome.
#[allow(unused_variables)]
pub trait Panel: gpui_base::dock::Panel {
    /// The short name shown when a tab bar has no room for the full title.
    ///
    /// Used by an already-collapsed tab group, where only the strip of tabs is
    /// on screen.
    fn tab_name(&self, cx: &App) -> Option<SharedString> {
        None
    }

    /// The panel's title, as an element rather than a string so a panel can
    /// draw an icon, a badge, or a styled fragment in the tab.
    fn title(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        t!("Dock.Unnamed")
    }

    /// Colors for the title, for a panel that wants its tab to stand out.
    fn title_style(&self, cx: &App) -> Option<TitleStyle> {
        None
    }

    /// An element pinned to the trailing end of the title bar.
    fn title_suffix(
        &mut self,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Option<impl IntoElement> {
        None::<gpui::Div>
    }

    /// Buttons for the title bar's toolbar.
    fn toolbar_buttons(
        &mut self,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Option<Vec<Button>> {
        None
    }

    /// Entries the panel adds to the title bar's ellipsis menu.
    fn dropdown_menu(
        &mut self,
        menu: PopupMenu,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> PopupMenu {
        menu
    }

    /// Where the zoom affordance appears, or `None` for nowhere.
    ///
    /// `None` withholds the whole affordance, not just the button: the
    /// [`ToggleZoom`](super::ToggleZoom) action refuses to zoom a panel that
    /// offers no control, so either answer alone is enough to mean "never
    /// zoom". Zooming *out* is never refused — a panel that stops offering
    /// the control while zoomed would otherwise strand the user with no way
    /// back.
    ///
    /// [`gpui_base::dock::Panel::zoomable`] is the other half: it decides
    /// whether zooming happens at all, and base refuses a zoom that fails it
    /// however the zoom was asked for.
    fn zoom_control(&self, cx: &App) -> Option<PanelControl> {
        Some(PanelControl::Menu)
    }

    /// Whether the tab group pads the panel's content when it draws it inside
    /// a tab bar.
    fn inner_padding(&self, cx: &App) -> bool {
        true
    }

    /// Whether the tab group draws a title bar above this panel when it is
    /// the only panel in its group.
    ///
    /// `false` for a panel that carries its own chrome. A group holding
    /// several panels still draws its tabs, so every panel stays reachable.
    fn title_bar(&self, cx: &App) -> bool {
        true
    }
}

/// Object-safe counterpart of [`Panel`], and the presentation half of the
/// handle a skin holds.
pub trait PanelView: gpui_base::dock::PanelView {
    fn tab_name(&self, cx: &App) -> Option<SharedString>;
    fn title(&self, window: &mut Window, cx: &mut App) -> AnyElement;
    fn title_style(&self, cx: &App) -> Option<TitleStyle>;
    fn title_suffix(&self, window: &mut Window, cx: &mut App) -> Option<AnyElement>;
    fn toolbar_buttons(&self, window: &mut Window, cx: &mut App) -> Option<Vec<Button>>;
    fn dropdown_menu(&self, menu: PopupMenu, window: &mut Window, cx: &mut App) -> PopupMenu;
    fn zoom_control(&self, cx: &App) -> Option<PanelControl>;
    fn inner_padding(&self, cx: &App) -> bool;
    fn title_bar(&self, cx: &App) -> bool;
}

impl<T: Panel> PanelView for Entity<T> {
    fn tab_name(&self, cx: &App) -> Option<SharedString> {
        self.read(cx).tab_name(cx)
    }

    fn title(&self, window: &mut Window, cx: &mut App) -> AnyElement {
        self.update(cx, |this, cx| this.title(window, cx).into_any_element())
    }

    fn title_style(&self, cx: &App) -> Option<TitleStyle> {
        self.read(cx).title_style(cx)
    }

    fn title_suffix(&self, window: &mut Window, cx: &mut App) -> Option<AnyElement> {
        self.update(cx, |this, cx| {
            this.title_suffix(window, cx)
                .map(|element| element.into_any_element())
        })
    }

    fn toolbar_buttons(&self, window: &mut Window, cx: &mut App) -> Option<Vec<Button>> {
        self.update(cx, |this, cx| this.toolbar_buttons(window, cx))
    }

    fn dropdown_menu(&self, menu: PopupMenu, window: &mut Window, cx: &mut App) -> PopupMenu {
        self.update(cx, |this, cx| this.dropdown_menu(menu, window, cx))
    }

    fn zoom_control(&self, cx: &App) -> Option<PanelControl> {
        self.read(cx).zoom_control(cx)
    }

    fn inner_padding(&self, cx: &App) -> bool {
        self.read(cx).inner_padding(cx)
    }

    fn title_bar(&self, cx: &App) -> bool {
        self.read(cx).title_bar(cx)
    }
}

/// The panel handle `gpui-base` holds on this crate's behalf.
///
/// Concrete on purpose. Base stores it as
/// `Arc<dyn gpui_base::dock::PanelView>`, and every renderer hook — the tab
/// bar most of all — gets it back with [`Self::of`], which is an `Any`
/// downcast to this one type. That is the only recovery Rust offers: the
/// sub-trait object `Arc<dyn PanelView>` cannot be reconstructed from base's
/// handle, but a concrete wrapper around it can be.
#[derive(Clone)]
pub struct PanelHandle(Arc<dyn PanelView>);

impl PanelHandle {
    pub fn new<P: Panel>(panel: Entity<P>) -> Self {
        Self(Arc::new(panel))
    }

    /// Wrap a presentation handle that is already erased.
    pub fn from_view(panel: Arc<dyn PanelView>) -> Self {
        Self(panel)
    }

    /// Recover the handle behind one of base's, or `None` when base is
    /// holding a panel this crate did not wrap — a bare `Entity<P>` handed
    /// straight to [`gpui_base::dock::DockLayout::panel`], say. A skin must
    /// draw something for that case; base's own
    /// [`gpui_base::dock::PanelView::panel_name`] is the fallback with no
    /// obligations on the panel author.
    pub fn of(panel: &Arc<dyn gpui_base::dock::PanelView>) -> Option<&Self> {
        panel.as_any().downcast_ref::<Self>()
    }

    /// The presentation handle, cloned out.
    ///
    /// Owned rather than borrowed because the title bar's ellipsis menu is
    /// built inside a `'static` callback: the menu closure outlives the
    /// `render_tab_bar` call that created it, so it cannot borrow from the
    /// render context it was made in.
    pub fn panel(&self) -> Arc<dyn PanelView> {
        self.0.clone()
    }
}

/// So a recovered handle answers the presentation trait directly:
/// `PanelHandle::of(panel)?.title(window, cx)`. Only [`Self::panel`] hands out
/// an owned clone, which is what a `'static` callback needs.
impl std::ops::Deref for PanelHandle {
    type Target = dyn PanelView;

    fn deref(&self) -> &Self::Target {
        &*self.0
    }
}

impl gpui_base::dock::PanelView for PanelHandle {
    fn panel_name(&self, cx: &App) -> &'static str {
        self.0.panel_name(cx)
    }

    fn panel_id(&self, cx: &App) -> PanelId {
        self.0.panel_id(cx)
    }

    fn closable(&self, cx: &App) -> bool {
        self.0.closable(cx)
    }

    fn zoomable(&self, cx: &App) -> bool {
        self.0.zoomable(cx)
    }

    fn visible(&self, cx: &App) -> bool {
        self.0.visible(cx)
    }

    fn set_active(&self, active: bool, window: &mut Window, cx: &mut App) {
        self.0.set_active(active, window, cx);
    }

    fn set_zoomed(&self, zoomed: bool, window: &mut Window, cx: &mut App) {
        self.0.set_zoomed(zoomed, window, cx);
    }

    fn on_added_to(&self, group: WeakEntity<TabGroup>, window: &mut Window, cx: &mut App) {
        self.0.on_added_to(group, window, cx);
    }

    fn on_removed(&self, window: &mut Window, cx: &mut App) {
        self.0.on_removed(window, cx);
    }

    fn view(&self) -> AnyView {
        self.0.view()
    }

    fn focus_handle(&self, cx: &App) -> FocusHandle {
        self.0.focus_handle(cx)
    }

    fn dump(&self, cx: &App) -> PanelState {
        self.0.dump(cx)
    }

    fn as_any(&self) -> &dyn Any {
        self
    }
}

/// Wrap `panel` so base carries its presentation across the renderer seam.
///
/// This is what every entry point into the dock wants:
/// `DockLayout::tabs().panel_view(panel_handle(story), cx)`,
/// `DockArea::add_panel_view(panel_handle(story), ..)`, and the closure a
/// [`register_panel`](gpui_base::dock::register_panel) builder returns.
///
/// Base's own `DockLayout::panel` and `DockArea::add_panel` also accept a
/// panel — a `gpui_component::dock::Panel` is a
/// `gpui_base::dock::Panel` — but they store the bare entity, and a skin
/// cannot recover presentation from one. Such a panel still docks, drags and
/// persists; it just draws its `panel_name` where its title would be.
pub fn panel_handle<P: Panel>(panel: Entity<P>) -> Arc<dyn gpui_base::dock::PanelView> {
    Arc::new(PanelHandle::new(panel))
}

#[cfg(test)]
mod tests {
    use std::{cell::RefCell, rc::Rc};

    use gpui::{
        AppContext as _, Div, Empty, EventEmitter, Focusable, InteractiveElement as _,
        ParentElement as _, Render, Stateful, Styled as _, TestAppContext, div,
    };
    use gpui_base::dock::{
        DockArea, DockAreaRenderer, DockLayout, PanelEvent, TabGroupContext, TabGroupRenderer,
    };

    use super::*;

    struct Probe {
        focus_handle: FocusHandle,
        tab_name: SharedString,
    }

    impl Probe {
        fn new(tab_name: &str, cx: &mut App) -> Entity<Self> {
            let tab_name = SharedString::from(tab_name.to_string());
            cx.new(|cx| Self {
                focus_handle: cx.focus_handle(),
                tab_name,
            })
        }
    }

    impl gpui_base::dock::Panel for Probe {
        fn panel_name(&self) -> &'static str {
            "Probe"
        }
    }

    impl Panel for Probe {
        fn tab_name(&self, _: &App) -> Option<SharedString> {
            Some(self.tab_name.clone())
        }
    }

    impl EventEmitter<PanelEvent> for Probe {}

    impl Focusable for Probe {
        fn focus_handle(&self, _: &App) -> FocusHandle {
            self.focus_handle.clone()
        }
    }

    impl Render for Probe {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Empty
        }
    }

    /// A read the skin took later, out of a handle it kept.
    type DeferredRead = Box<dyn Fn(&mut Window, &mut App) -> Option<SharedString>>;

    #[derive(Default)]
    struct Recovered {
        /// What the tab bar read off each panel while it drew, or `None` for a
        /// panel it could not recover.
        tab_names: Vec<Option<SharedString>>,
        /// A read the tab bar deferred, the way an ellipsis menu defers
        /// building its items.
        deferred: Option<DeferredRead>,
    }

    /// The skin: a tab bar that recovers this crate's handle out of base's and
    /// reads presentation off it.
    struct Skin {
        recovered: Rc<RefCell<Recovered>>,
    }

    impl TabGroupRenderer for Skin {
        fn render_tab_bar(
            &self,
            group: &TabGroupContext,
            window: &mut Window,
            cx: &mut App,
        ) -> AnyElement {
            let mut recovered = self.recovered.borrow_mut();
            let mut tabs = Vec::new();
            for panel in group.panels() {
                let Some(handle) = PanelHandle::of(panel) else {
                    recovered.tab_names.push(None);
                    continue;
                };
                recovered.tab_names.push(handle.tab_name(cx));

                // `title` takes the window and a mutable app while `group` is
                // still borrowed, which is the shape every tab in a real tab
                // bar is built from.
                tabs.push(handle.title(window, cx));

                // And the shape an ellipsis menu needs: an owned handle,
                // called back with a window and an app long after this borrow
                // of `group` is gone.
                let panel = handle.panel();
                recovered.deferred = Some(Box::new(move |window, cx| {
                    let _ = panel.title(window, cx);
                    panel.tab_name(cx)
                }));
            }

            div().children(tabs).into_any_element()
        }
    }

    impl DockAreaRenderer for Skin {
        fn frame(&self, _: &mut Window, _: &mut App) -> Stateful<Div> {
            div().id("skin-dock-area").size_full()
        }

        fn tab_group_renderer(&self) -> Rc<dyn TabGroupRenderer> {
            Rc::new(Skin {
                recovered: self.recovered.clone(),
            })
        }
    }

    /// The seam this module exists for: a panel wrapped in a [`PanelHandle`],
    /// installed through base's `DockLayout`, comes back to the skin's tab bar
    /// as a handle it can read presentation off.
    ///
    /// Nothing in `TabGroupContext` is typed to this crate — the renderer
    /// holds `Arc<dyn gpui_base::dock::PanelView>` — so if the `Any` downcast
    /// stopped working the recorded name would be `None` and this fails.
    #[gpui::test]
    fn the_tab_bar_recovers_presentation_from_a_base_panel_handle(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let _ = gpui_base::Theme::global_mut(cx);
        });
        let recovered = Rc::new(RefCell::new(Recovered::default()));
        let skin = Rc::new(Skin {
            recovered: recovered.clone(),
        });

        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("seam", None, window, cx).with_renderer(skin)
        });

        cx.update(|window, cx| {
            let panel = PanelHandle::new(Probe::new("Probe Tab", cx));
            let layout = DockLayout::tabs().panel_view(Arc::new(panel), cx);
            area.update(cx, |area, cx| area.set_center(layout, window, cx));
        });
        cx.run_until_parked();
        recovered.borrow_mut().tab_names.clear();
        cx.update(|window, cx| window.draw(cx).clear(cx));

        assert_eq!(
            recovered.borrow().tab_names,
            vec![Some(SharedString::from("Probe Tab"))],
            "the skin read its own panel trait off base's handle"
        );

        // And the handle it kept still answers once the frame that recovered
        // it is over, which is what an ellipsis menu's callback needs.
        let deferred = recovered.borrow_mut().deferred.take().expect("kept");
        let later = cx.update(|window, cx| deferred(window, cx));
        assert_eq!(later, Some(SharedString::from("Probe Tab")));
    }

    /// A panel rebuilt from persisted state is recoverable too. This needs no
    /// new entry point: [`gpui_base::dock::register_panel`] already takes a
    /// builder returning `Arc<dyn gpui_base::dock::PanelView>`, so the skin's
    /// builder returns a [`PanelHandle`] and base stores that handle as-is.
    #[gpui::test]
    fn a_panel_rebuilt_from_persisted_state_is_recoverable(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let _ = gpui_base::Theme::global_mut(cx);
        });
        let recovered = Rc::new(RefCell::new(Recovered::default()));
        let skin = Rc::new(Skin {
            recovered: recovered.clone(),
        });

        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("seam", None, window, cx).with_renderer(skin)
        });

        cx.update(|window, cx| {
            gpui_base::dock::register_panel(cx, "Probe", |_, _, cx| {
                Arc::new(PanelHandle::new(Probe::new("Restored Tab", cx)))
                    as Arc<dyn gpui_base::dock::PanelView>
            });
            let panel = PanelHandle::new(Probe::new("Probe Tab", cx));
            let layout = DockLayout::tabs().panel_view(Arc::new(panel), cx);
            area.update(cx, |area, cx| area.set_center(layout, window, cx));
        });
        cx.run_until_parked();

        let state = cx.read(|cx| area.read(cx).dump(cx));
        cx.update(|window, cx| area.update(cx, |area, cx| area.load(state, window, cx).unwrap()));
        cx.run_until_parked();
        recovered.borrow_mut().tab_names.clear();
        cx.update(|window, cx| window.draw(cx).clear(cx));

        assert_eq!(
            recovered.borrow().tab_names,
            vec![Some(SharedString::from("Restored Tab"))],
            "the rebuilt panel reached the tab bar as a handle, not a bare entity"
        );
    }

    /// The other half of [`PanelHandle::of`]'s contract: a panel base was
    /// handed directly is not this crate's handle, and the skin is told so
    /// rather than being handed something wrong.
    #[gpui::test]
    fn a_panel_base_was_handed_directly_is_not_recoverable(cx: &mut TestAppContext) {
        cx.update(|cx| {
            let _ = gpui_base::Theme::global_mut(cx);
        });
        let recovered = Rc::new(RefCell::new(Recovered::default()));
        let skin = Rc::new(Skin {
            recovered: recovered.clone(),
        });

        let (area, cx) = cx.add_window_view(|window, cx| {
            DockArea::new("seam", None, window, cx).with_renderer(skin)
        });

        cx.update(|window, cx| {
            let layout = DockLayout::tabs().panel(Probe::new("Probe Tab", cx));
            area.update(cx, |area, cx| area.set_center(layout, window, cx));
        });
        cx.run_until_parked();
        recovered.borrow_mut().tab_names.clear();
        cx.update(|window, cx| window.draw(cx).clear(cx));

        assert_eq!(
            recovered.borrow().tab_names,
            vec![None],
            "an unwrapped panel is reported as unrecoverable, not wrongly recovered"
        );
    }
}
