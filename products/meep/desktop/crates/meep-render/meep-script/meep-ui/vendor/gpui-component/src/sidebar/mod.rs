use crate::{
    ActiveTheme, Collapsible, Icon, IconName, Side, Sizable, StyledExt,
    button::{Button, ButtonVariants},
    h_flex,
    scroll::ScrollableElement,
    v_flex,
};
use gpui::{
    AbsoluteLength, AnyElement, App, ClickEvent, DefiniteLength, EdgesRefinement, ElementId,
    InteractiveElement as _, IntoElement, Length, ListAlignment, ListState, ParentElement, Pixels,
    RenderOnce, SharedString, StyleRefinement, Styled, Window, div, list, prelude::FluentBuilder,
    px,
};
use std::{rc::Rc, time::Duration};

use crate::animation::{EffectTransition, ease_in_out_cubic};

mod footer;
mod group;
mod header;
mod menu;
pub use footer::*;
pub use group::*;
pub use header::*;
pub use menu::*;

const DEFAULT_WIDTH: Pixels = px(255.);
const COLLAPSED_WIDTH: Pixels = px(48.);
const SIDEBAR_TRANSITION_DURATION: Duration = Duration::from_millis(200);

/// The way a [`Sidebar`] behaves when it is collapsed.
///
/// This follows the shadcn/ui sidebar modes:
/// - [`SidebarCollapsible::Icon`] collapses the sidebar to icon width.
/// - [`SidebarCollapsible::Offcanvas`] slides the sidebar out and releases its layout width.
/// - [`SidebarCollapsible::None`] keeps the sidebar expanded and ignores collapsed state.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum SidebarCollapsible {
    /// Collapse the sidebar to icon width.
    #[default]
    Icon,
    /// Collapse the sidebar completely out of the layout.
    Offcanvas,
    /// Disable sidebar collapse.
    None,
}

impl From<bool> for SidebarCollapsible {
    fn from(collapsible: bool) -> Self {
        if collapsible { Self::Icon } else { Self::None }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum SidebarWrapperLayout {
    None,
    Static { width: Pixels },
    Animated { target_width: Pixels },
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct SidebarLayout {
    icon_collapsed: bool,
    offcanvas_collapsed: bool,
    align_child_to_end: bool,
    wrapper: SidebarWrapperLayout,
}

impl SidebarLayout {
    fn new(
        collapsible: SidebarCollapsible,
        collapsed: bool,
        expanded_width: Option<Pixels>,
        side: Side,
    ) -> Self {
        let collapsed = collapsed && collapsible != SidebarCollapsible::None;
        let wrapper = match collapsible {
            SidebarCollapsible::None => SidebarWrapperLayout::None,
            SidebarCollapsible::Icon => match expanded_width {
                Some(expanded_width) => SidebarWrapperLayout::Animated {
                    target_width: if collapsed {
                        COLLAPSED_WIDTH
                    } else {
                        expanded_width
                    },
                },
                None => SidebarWrapperLayout::None,
            },
            SidebarCollapsible::Offcanvas => match (expanded_width, collapsed) {
                (Some(_), true) => SidebarWrapperLayout::Animated {
                    target_width: px(0.),
                },
                (Some(expanded_width), false) => SidebarWrapperLayout::Animated {
                    target_width: expanded_width,
                },
                (None, true) => SidebarWrapperLayout::Static { width: px(0.) },
                (None, false) => SidebarWrapperLayout::None,
            },
        };
        let align_child_to_end = match collapsible {
            SidebarCollapsible::Offcanvas => side.is_left(),
            _ => side.is_right(),
        };

        Self {
            icon_collapsed: collapsed && collapsible == SidebarCollapsible::Icon,
            offcanvas_collapsed: collapsed && collapsible == SidebarCollapsible::Offcanvas,
            align_child_to_end,
            wrapper,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct SidebarAnimationState {
    from_width: Pixels,
    target_width: Pixels,
    render_child: bool,
    hide_scheduled: bool,
    hide_request: u64,
}

impl SidebarAnimationState {
    fn new(target_width: Pixels, render_child: bool) -> Self {
        Self {
            from_width: target_width,
            target_width,
            render_child,
            hide_scheduled: false,
            hide_request: 0,
        }
    }

    fn needs_update(&self, target_width: Pixels, offcanvas_collapsed: bool) -> bool {
        let child_state_changed = if offcanvas_collapsed {
            self.render_child && !self.hide_scheduled
        } else {
            !self.render_child || self.hide_scheduled
        };

        self.target_width != target_width || child_state_changed
    }

    fn update_target(&mut self, target_width: Pixels, offcanvas_collapsed: bool) -> Option<u64> {
        if self.target_width != target_width {
            self.from_width = self.target_width;
            self.target_width = target_width;
        }

        if offcanvas_collapsed {
            if self.render_child && !self.hide_scheduled {
                self.hide_scheduled = true;
                self.hide_request = self.hide_request.wrapping_add(1);
                Some(self.hide_request)
            } else {
                None
            }
        } else {
            self.render_child = true;
            if self.hide_scheduled {
                self.hide_request = self.hide_request.wrapping_add(1);
            }
            self.hide_scheduled = false;
            None
        }
    }

    fn finish_hide(&mut self, request: u64) -> bool {
        if self.render_child
            && self.hide_scheduled
            && self.hide_request == request
            && self.target_width == px(0.)
        {
            self.render_child = false;
            self.hide_scheduled = false;
            true
        } else {
            false
        }
    }
}

fn sidebar_wrapper(
    id: impl Into<ElementId>,
    align_child_to_end: bool,
) -> impl ParentElement + IntoElement + Styled {
    div()
        .id(id)
        .flex()
        .h_full()
        .flex_shrink_0()
        .overflow_hidden()
        .when(align_child_to_end, |this| this.justify_end())
}

fn sidebar_expanded_width(style: &StyleRefinement) -> Option<Pixels> {
    match style.size.width {
        Some(Length::Definite(DefiniteLength::Absolute(AbsoluteLength::Pixels(px)))) => Some(px),
        Some(_) => None,
        None => Some(DEFAULT_WIDTH),
    }
}

fn sidebar_animation_id(id: &ElementId, from: Pixels, to: Pixels) -> ElementId {
    ElementId::NamedInteger(
        format!("{id}-anim-w").into(),
        (from.as_f32().to_bits() as u64) << 32 | to.as_f32().to_bits() as u64,
    )
}

pub trait SidebarItem: Collapsible + Clone {
    fn render(
        self,
        id: impl Into<ElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> impl IntoElement;
}

/// A Sidebar element that can contain collapsible child elements.
#[derive(IntoElement)]
pub struct Sidebar<E: SidebarItem + 'static> {
    id: ElementId,
    style: StyleRefinement,
    content: Vec<E>,
    /// header view
    header: Option<AnyElement>,
    /// footer view
    footer: Option<AnyElement>,
    /// The side of the sidebar
    side: Side,
    collapsible: SidebarCollapsible,
    collapsed: bool,
}

impl<E: SidebarItem> Sidebar<E> {
    /// Create a new Sidebar with the given ID.
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            content: vec![],
            header: None,
            footer: None,
            side: Side::Left,
            collapsible: SidebarCollapsible::Icon,
            collapsed: false,
        }
    }

    /// Set the side of the sidebar.
    ///
    /// Default is `Side::Left`.
    pub fn side(mut self, side: Side) -> Self {
        self.side = side;
        self
    }

    /// Set how the sidebar collapses.
    ///
    /// Passing `true` keeps the previous behavior and maps to
    /// [`SidebarCollapsible::Icon`]. Passing `false` maps to
    /// [`SidebarCollapsible::None`].
    pub fn collapsible(mut self, collapsible: impl Into<SidebarCollapsible>) -> Self {
        self.collapsible = collapsible.into();
        self
    }

    /// Set the sidebar to be collapsed
    pub fn collapsed(mut self, collapsed: bool) -> Self {
        self.collapsed = collapsed;
        self
    }

    /// Set the header of the sidebar.
    pub fn header(mut self, header: impl IntoElement) -> Self {
        self.header = Some(header.into_any_element());
        self
    }

    /// Set the footer of the sidebar.
    pub fn footer(mut self, footer: impl IntoElement) -> Self {
        self.footer = Some(footer.into_any_element());
        self
    }

    /// Add a child element to the sidebar, the child must implement `Collapsible`
    pub fn child(mut self, child: E) -> Self {
        self.content.push(child);
        self
    }

    /// Add multiple children to the sidebar, the children must implement `Collapsible`
    pub fn children(mut self, children: impl IntoIterator<Item = E>) -> Self {
        self.content.extend(children);
        self
    }
}

/// Toggle button to collapse/expand the [`Sidebar`].
#[derive(IntoElement)]
pub struct SidebarToggleButton {
    btn: Button,
    collapsed: bool,
    side: Side,
    on_click: Option<Rc<dyn Fn(&ClickEvent, &mut Window, &mut App)>>,
}

impl SidebarToggleButton {
    /// Create a new SidebarToggleButton.
    pub fn new() -> Self {
        Self {
            btn: Button::new("collapse").ghost().small(),
            collapsed: false,
            side: Side::Left,
            on_click: None,
        }
    }

    /// Set the side of the toggle button.
    ///
    /// Default is `Side::Left`.
    pub fn side(mut self, side: Side) -> Self {
        self.side = side;
        self
    }

    /// Set the collapsed state of the toggle button.
    pub fn collapsed(mut self, collapsed: bool) -> Self {
        self.collapsed = collapsed;
        self
    }

    /// Set the accessibility label of the toggle button.
    ///
    /// The default toggle is icon-only; without an explicit label it has no
    /// accessible name.
    pub fn accessibility_label(mut self, label: impl Into<SharedString>) -> Self {
        self.btn = self.btn.accessibility_label(label);
        self
    }

    /// Add a click handler to the toggle button.
    pub fn on_click(
        mut self,
        on_click: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_click = Some(Rc::new(on_click));
        self
    }
}

impl RenderOnce for SidebarToggleButton {
    fn render(self, _window: &mut Window, _cx: &mut App) -> impl IntoElement {
        let collapsed = self.collapsed;
        let on_click = self.on_click.clone();

        let icon = if collapsed {
            if self.side.is_left() {
                IconName::PanelLeftOpen
            } else {
                IconName::PanelRightOpen
            }
        } else {
            if self.side.is_left() {
                IconName::PanelLeftClose
            } else {
                IconName::PanelRightClose
            }
        };

        self.btn
            .when_some(on_click, |this, on_click| {
                this.on_click(move |ev, window, cx| {
                    on_click(ev, window, cx);
                })
            })
            .icon(Icon::new(icon).size_4())
    }
}

impl<E: SidebarItem> Styled for Sidebar<E> {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl<E: SidebarItem> RenderOnce for Sidebar<E> {
    fn render(mut self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        self.style.padding = EdgesRefinement::default();

        let id = self.id;
        let content_len = self.content.len();
        let overdraw = px(window.viewport_size().height.as_f32() * 0.3);
        let list_state = window
            .use_keyed_state(
                SharedString::from(format!("{}-list-state", id)),
                cx,
                |_, _| ListState::new(content_len, ListAlignment::Top, overdraw),
            )
            .read(cx)
            .clone();
        if list_state.item_count() != content_len {
            list_state.reset(content_len);
        }

        // Determine effective expanded width from user's custom style or default.
        // Non-pixel widths still render correctly, but cannot use pixel width transitions.
        let expanded_width = sidebar_expanded_width(&self.style);
        let layout =
            SidebarLayout::new(self.collapsible, self.collapsed, expanded_width, self.side);

        // Sidebar content renders at its target width immediately. A wrapper
        // div animates clip-width for smooth transitions without re-laying out
        // sidebar content each animation frame.
        let sidebar = v_flex()
            .id(id.clone())
            .flex_shrink_0()
            .h_full()
            .overflow_hidden()
            .relative()
            .bg(cx.theme().tokens.sidebar)
            .text_color(cx.theme().sidebar_foreground)
            .border_color(cx.theme().sidebar_border)
            .map(|this| match self.side {
                Side::Left => this.border_r_1(),
                Side::Right => this.border_l_1(),
            })
            .when(self.style.size.width.is_none(), |this| {
                this.w(DEFAULT_WIDTH)
            })
            .refine_style(&self.style)
            .when(layout.icon_collapsed, |this| {
                this.w(COLLAPSED_WIDTH).gap_2()
            })
            .when_some(self.header.take(), |this, header| {
                this.child(
                    h_flex()
                        .id("header")
                        .pt_3()
                        .px_3()
                        .gap_2()
                        .when(layout.icon_collapsed, |this| this.pt_2().px_2())
                        .child(header),
                )
            })
            .child(
                v_flex().id("content").flex_1().min_h_0().child(
                    v_flex()
                        .id("inner")
                        .size_full()
                        .px_3()
                        .gap_y_3()
                        .when(layout.icon_collapsed, |this| this.p_2())
                        .child(gpui_base::ScrollBounce::new(
                            "bounce",
                            &list_state,
                            list(list_state.clone(), {
                                move |ix, window, cx| {
                                    let group = self.content.get(ix).cloned();
                                    let is_first = ix == 0;
                                    let is_last =
                                        content_len > 0 && ix == content_len.saturating_sub(1);
                                    div()
                                        .id(ix)
                                        .when_some(group, |this, group| {
                                            this.child(
                                                group
                                                    .collapsed(layout.icon_collapsed)
                                                    .render(ix, window, cx)
                                                    .into_any_element(),
                                            )
                                        })
                                        .when(is_first, |this| this.pt_3())
                                        .when(is_last, |this| this.pb_3())
                                        .into_any_element()
                                }
                            })
                            .size_full(),
                        ))
                        .vertical_scrollbar(&list_state),
                ),
            )
            .when_some(self.footer.take(), |this, footer| {
                this.child(
                    h_flex()
                        .id("footer")
                        .pb_3()
                        .px_3()
                        .gap_2()
                        .when(layout.icon_collapsed, |this| this.pt_2().px_2())
                        .child(footer),
                )
            });

        let target_width = match layout.wrapper {
            SidebarWrapperLayout::None => return sidebar.into_any_element(),
            SidebarWrapperLayout::Static { width } => {
                return sidebar_wrapper(format!("{}-anim", id), layout.align_child_to_end)
                    .w(width)
                    .when(!layout.offcanvas_collapsed, |this| this.child(sidebar))
                    .into_any_element();
            }
            SidebarWrapperLayout::Animated { target_width } => target_width,
        };

        // Store animation state in keyed state so it remains stable across
        // re-renders (GPUI re-renders the whole tree on each animation frame).
        // The target width is derived from the current layout, so changes to
        // collapsible mode or expanded width are handled even if `collapsed`
        // itself does not change. Offcanvas keeps content mounted while the
        // close transition runs, then unmounts it so hidden controls leave the
        // tab order.
        let animation_state = window.use_keyed_state(format!("{}-anim-w", id), cx, |_, _| {
            SidebarAnimationState::new(target_width, !layout.offcanvas_collapsed)
        });

        let hide_request = if animation_state
            .read(cx)
            .needs_update(target_width, layout.offcanvas_collapsed)
        {
            animation_state.update(cx, |state, _| {
                state.update_target(target_width, layout.offcanvas_collapsed)
            })
        } else {
            None
        };
        if let Some(hide_request) = hide_request {
            cx.spawn({
                let animation_state = animation_state.clone();
                async move |cx| {
                    cx.background_executor()
                        .timer(SIDEBAR_TRANSITION_DURATION)
                        .await;
                    _ = animation_state.update(cx, |state, cx| {
                        if state.finish_hide(hide_request) {
                            cx.notify();
                        }
                    });
                }
            })
            .detach();
        }
        let animation_state = *animation_state.read(cx);
        let from_w = animation_state.from_width;
        let to_w = animation_state.target_width;

        let wrapper = sidebar_wrapper(format!("{}-anim", id), layout.align_child_to_end)
            .when(animation_state.render_child, |this| this.child(sidebar));

        EffectTransition::new(SIDEBAR_TRANSITION_DURATION)
            .ease(ease_in_out_cubic)
            .width(from_w, to_w)
            .apply(wrapper, sidebar_animation_id(&id, from_w, to_w))
            .into_any_element()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn layout(
        collapsible: SidebarCollapsible,
        collapsed: bool,
        expanded_width: Option<Pixels>,
        side: Side,
    ) -> SidebarLayout {
        SidebarLayout::new(collapsible, collapsed, expanded_width, side)
    }

    #[test]
    fn bool_collapsible_should_remain_backward_compatible() {
        assert_eq!(SidebarCollapsible::from(true), SidebarCollapsible::Icon);
        assert_eq!(SidebarCollapsible::from(false), SidebarCollapsible::None);
    }

    #[test]
    fn icon_collapsed_should_use_icon_width_and_icon_rendering() {
        let layout = layout(SidebarCollapsible::Icon, true, Some(px(240.)), Side::Left);

        assert!(layout.icon_collapsed);
        assert!(!layout.offcanvas_collapsed);
        assert!(!layout.align_child_to_end);
        assert_eq!(
            layout.wrapper,
            SidebarWrapperLayout::Animated {
                target_width: COLLAPSED_WIDTH,
            }
        );
    }

    #[test]
    fn icon_expanded_should_use_expanded_width() {
        let layout = layout(SidebarCollapsible::Icon, false, Some(px(240.)), Side::Left);

        assert!(!layout.icon_collapsed);
        assert!(!layout.offcanvas_collapsed);
        assert_eq!(
            layout.wrapper,
            SidebarWrapperLayout::Animated {
                target_width: px(240.),
            }
        );
    }

    #[test]
    fn icon_expanded_with_non_pixel_width_should_keep_original_layout() {
        let layout = layout(SidebarCollapsible::Icon, false, None, Side::Left);

        assert!(!layout.icon_collapsed);
        assert!(!layout.offcanvas_collapsed);
        assert_eq!(layout.wrapper, SidebarWrapperLayout::None);
    }

    #[test]
    fn none_should_ignore_collapsed_state() {
        let layout = layout(SidebarCollapsible::None, true, Some(px(240.)), Side::Right);

        assert!(!layout.icon_collapsed);
        assert!(!layout.offcanvas_collapsed);
        assert!(layout.align_child_to_end);
        assert_eq!(layout.wrapper, SidebarWrapperLayout::None);
    }

    #[test]
    fn offcanvas_collapsed_with_pixel_width_should_animate_to_zero() {
        let layout = layout(
            SidebarCollapsible::Offcanvas,
            true,
            Some(px(240.)),
            Side::Left,
        );

        assert!(!layout.icon_collapsed);
        assert!(layout.offcanvas_collapsed);
        assert!(layout.align_child_to_end);
        assert_eq!(
            layout.wrapper,
            SidebarWrapperLayout::Animated {
                target_width: px(0.),
            }
        );
    }

    #[test]
    fn offcanvas_expanded_with_pixel_width_should_use_expanded_width() {
        let layout = layout(
            SidebarCollapsible::Offcanvas,
            false,
            Some(px(240.)),
            Side::Left,
        );

        assert!(!layout.icon_collapsed);
        assert!(!layout.offcanvas_collapsed);
        assert_eq!(
            layout.wrapper,
            SidebarWrapperLayout::Animated {
                target_width: px(240.),
            }
        );
    }

    #[test]
    fn offcanvas_collapsed_with_non_pixel_width_should_statically_release_layout() {
        let layout = layout(SidebarCollapsible::Offcanvas, true, None, Side::Left);

        assert!(!layout.icon_collapsed);
        assert!(layout.offcanvas_collapsed);
        assert_eq!(
            layout.wrapper,
            SidebarWrapperLayout::Static { width: px(0.) }
        );
    }

    #[test]
    fn offcanvas_expanded_with_non_pixel_width_should_keep_original_layout() {
        let layout = layout(SidebarCollapsible::Offcanvas, false, None, Side::Left);

        assert!(!layout.icon_collapsed);
        assert!(!layout.offcanvas_collapsed);
        assert_eq!(layout.wrapper, SidebarWrapperLayout::None);
    }

    #[test]
    fn offcanvas_should_anchor_child_toward_the_content_edge() {
        let left = layout(
            SidebarCollapsible::Offcanvas,
            true,
            Some(px(240.)),
            Side::Left,
        );
        let right = layout(
            SidebarCollapsible::Offcanvas,
            true,
            Some(px(240.)),
            Side::Right,
        );

        assert!(left.align_child_to_end);
        assert!(!right.align_child_to_end);
    }

    #[test]
    fn animation_id_should_be_scoped_to_sidebar_id() {
        let from = px(240.);
        let to = COLLAPSED_WIDTH;

        assert_ne!(
            sidebar_animation_id(&ElementId::Name("sidebar-a".into()), from, to),
            sidebar_animation_id(&ElementId::Name("sidebar-b".into()), from, to)
        );
    }

    #[test]
    fn animation_state_should_keep_child_until_offcanvas_hide_finishes() {
        let mut state = SidebarAnimationState::new(px(240.), true);

        let request = state.update_target(px(0.), true);

        assert_eq!(request, Some(1));
        assert_eq!(state.from_width, px(240.));
        assert_eq!(state.target_width, px(0.));
        assert!(state.render_child);

        assert!(state.finish_hide(1));

        assert!(!state.render_child);
        assert!(!state.hide_scheduled);
    }

    #[test]
    fn animation_state_should_not_reschedule_pending_offcanvas_hide() {
        let mut state = SidebarAnimationState::new(px(240.), true);

        let request = state.update_target(px(0.), true);

        assert_eq!(request, Some(1));
        assert!(!state.needs_update(px(0.), true));
        assert_eq!(state.update_target(px(0.), true), None);
        assert_eq!(state.hide_request, 1);
    }

    #[test]
    fn animation_state_should_cancel_pending_hide_when_reexpanded() {
        let mut state = SidebarAnimationState::new(px(240.), true);

        let request = state.update_target(px(0.), true).unwrap();
        state.update_target(px(240.), false);

        assert!(!state.finish_hide(request));
        assert!(state.render_child);
        assert!(!state.hide_scheduled);
        assert_eq!(state.from_width, px(0.));
        assert_eq!(state.target_width, px(240.));
    }

    #[test]
    fn animation_state_should_ignore_stale_hide_request() {
        let mut state = SidebarAnimationState::new(px(240.), true);

        let request = state.update_target(px(0.), true).unwrap();
        state.update_target(px(240.), false);
        state.update_target(px(0.), true);

        assert!(!state.finish_hide(request));
        assert!(state.render_child);
        assert!(state.hide_scheduled);
    }

    #[test]
    fn animation_state_should_start_hidden_when_initially_offcanvas_collapsed() {
        let state = SidebarAnimationState::new(px(0.), false);

        assert!(!state.render_child);
        assert_eq!(state.from_width, px(0.));
        assert_eq!(state.target_width, px(0.));
    }
}
