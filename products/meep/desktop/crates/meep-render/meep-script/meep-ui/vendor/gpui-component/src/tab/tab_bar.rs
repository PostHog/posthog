use std::{cell::RefCell, rc::Rc};

use gpui::{
    Anchor, AnyElement, App, Background, Bounds, ClickEvent, Edges, ElementId, Entity, EntityId,
    InteractiveElement, IntoElement, ParentElement, Pixels, RenderOnce, ScrollHandle, SharedString,
    StatefulInteractiveElement as _, StyleRefinement, Styled, Window, div, point,
    prelude::FluentBuilder as _, px,
};
use gpui_base::spring;
use rust_i18n::t;
use smallvec::SmallVec;

use super::{
    Tab, TabVariant,
    tab::{FOLDER_TAB_GAP, FolderTabMetrics},
};
use crate::button::{Button, ButtonVariants as _};
use crate::menu::{DropdownMenu as _, PopupMenuItem};
use crate::scroll::ScrollableMask;
use crate::{
    ActiveTheme, ElementExt, Icon, InteractiveElementExt as _, Selectable, Sizable, Size,
    StyledExt, h_flex, styled::raised_shadow,
};

struct TabIndicatorBounds {
    container: Bounds<Pixels>,
    tabs: Vec<Bounds<Pixels>>,
    /// Where the last render placed the indicator: its left edge from the
    /// first tab's, and its width (zero before the tabs were measured).
    placed: (Pixels, Pixels),
}

impl TabIndicatorBounds {
    fn new(num_tabs: usize) -> Self {
        Self {
            container: Bounds::default(),
            tabs: vec![Bounds::default(); num_tabs],
            placed: (px(0.), px(0.)),
        }
    }

    fn resize(&mut self, num_tabs: usize) {
        self.tabs.resize(num_tabs, Bounds::default());
    }
}

/// A TabBar element that contains multiple [`Tab`] items.
#[derive(IntoElement)]
pub struct TabBar {
    id: ElementId,
    base: gpui_base::Tabs,
    style: StyleRefinement,
    scroll_handle: Option<ScrollHandle>,
    prefix: Option<AnyElement>,
    suffix: Option<AnyElement>,
    children: SmallVec<[Tab; 2]>,
    last_empty_space: AnyElement,
    selected_index: Option<usize>,
    variant: TabVariant,
    size: Size,
    menu: bool,
    max_width: Option<Pixels>,
    on_click: Option<Rc<dyn Fn(&usize, &mut Window, &mut App) + 'static>>,
}

impl TabBar {
    /// Create a new TabBar.
    pub fn new(id: impl Into<ElementId>) -> Self {
        let id = id.into();
        Self {
            id: id.clone(),
            base: gpui_base::Tabs::new(id).px(px(-1.)),
            style: StyleRefinement::default(),
            children: SmallVec::new(),
            scroll_handle: None,
            prefix: None,
            suffix: None,
            variant: TabVariant::default(),
            size: Size::default(),
            last_empty_space: div().w_3().into_any_element(),
            selected_index: None,
            on_click: None,
            menu: false,
            max_width: None,
        }
    }

    /// Set the Tab variant, all children will inherit the variant.
    pub fn with_variant(mut self, variant: TabVariant) -> Self {
        self.variant = variant;
        self
    }

    /// Set the Tab variant to Pill, all children will inherit the variant.
    pub fn pill(mut self) -> Self {
        self.variant = TabVariant::Pill;
        self
    }

    /// Set the Tab variant to Outline, all children will inherit the variant.
    pub fn outline(mut self) -> Self {
        self.variant = TabVariant::Outline;
        self
    }

    /// Set the Tab variant to Segmented, all children will inherit the variant.
    pub fn segmented(mut self) -> Self {
        self.variant = TabVariant::Segmented;
        self
    }

    /// Set the Tab variant to Underline, all children will inherit the variant.
    pub fn underline(mut self) -> Self {
        self.variant = TabVariant::Underline;
        self
    }

    /// Set the Tab variant to Folder, all children will inherit the variant.
    pub fn folder(mut self) -> Self {
        self.variant = TabVariant::Folder;
        self
    }

    /// Set whether to show the menu button when tabs overflow, default is false.
    pub fn menu(mut self, menu: bool) -> Self {
        self.menu = menu;
        self
    }

    /// Set the maximum width of each tab. Labels longer than this width are
    /// truncated with an ellipsis. Does not apply to icon-only tabs. The
    /// overflow menu still shows the full label.
    pub fn max_width(mut self, width: impl Into<Pixels>) -> Self {
        self.max_width = Some(width.into());
        self
    }

    /// Track the scroll of the TabBar.
    ///
    /// Clicking a tab scrolls it into view along with part of the next tab,
    /// but changing the selection, the tabs or the layout does not. Use the
    /// tracked [`ScrollHandle`] to request an explicit reveal when needed.
    pub fn track_scroll(mut self, scroll_handle: &ScrollHandle) -> Self {
        self.scroll_handle = Some(scroll_handle.clone());
        self
    }

    /// Set the prefix element of the TabBar
    pub fn prefix(mut self, prefix: impl IntoElement) -> Self {
        self.prefix = Some(prefix.into_any_element());
        self
    }

    /// Set the suffix element of the TabBar
    pub fn suffix(mut self, suffix: impl IntoElement) -> Self {
        self.suffix = Some(suffix.into_any_element());
        self
    }

    /// Add children of the TabBar, all children will inherit the variant.
    pub fn children(mut self, children: impl IntoIterator<Item = impl Into<Tab>>) -> Self {
        self.children.extend(children.into_iter().map(Into::into));
        self
    }

    /// Add child of the TabBar, tab will inherit the variant.
    pub fn child(mut self, child: impl Into<Tab>) -> Self {
        self.children.push(child.into());
        self
    }

    /// Set the selected index of the TabBar.
    pub fn selected_index(mut self, index: usize) -> Self {
        self.selected_index = Some(index);
        self
    }

    /// Set the last empty space element of the TabBar.
    pub fn last_empty_space(mut self, last_empty_space: impl IntoElement) -> Self {
        self.last_empty_space = last_empty_space.into_any_element();
        self
    }

    /// Set the on_click callback of the TabBar, the first parameter is the index of the clicked tab.
    ///
    /// When this is set, the children's on_click will be ignored.
    pub fn on_click<F>(mut self, on_click: F) -> Self
    where
        F: Fn(&usize, &mut Window, &mut App) + 'static,
    {
        self.on_click = Some(Rc::new(on_click));
        self
    }

    /// Render the sliding indicator element for animated tab switching.
    ///
    /// Returns the indicator element together with the current animation
    /// `epoch`, which increments on every tab switch. Tabs key their own
    /// transitions (e.g. text color fade) on this epoch so they restart in sync
    /// with the indicator slide.
    fn render_indicator(
        &self,
        bounds_rc: &Option<Rc<RefCell<TabIndicatorBounds>>>,
        window: &mut Window,
        cx: &mut App,
    ) -> Option<(AnyElement, u64)> {
        let has_indicator = matches!(
            self.variant,
            TabVariant::Segmented | TabVariant::Pill | TabVariant::Underline
        );
        let num_tabs = self.children.len();
        let selected_ix = self.selected_index.unwrap_or(usize::MAX);

        if !(has_indicator && num_tabs > 0 && selected_ix < num_tabs) {
            return None;
        }

        let prev_key = format!("{}-tab-prev", self.id);
        let anim_key = format!("{}-tab-anim", self.id);
        let init_key = format!("{}-tab-init", self.id);

        let prev_selected = window.use_keyed_state(prev_key, cx, |_, _| selected_ix);
        // (to_left, to_width, epoch)
        let anim_params = window.use_keyed_state(anim_key, cx, |_, _| (px(0.), px(0.), 0u64));
        let initialized = window.use_keyed_state(init_key, cx, |_, _| false);

        // First frame: trigger re-render to capture bounds via on_prepaint
        if !*initialized.read(cx) {
            initialized.update(cx, |v, _| *v = true);
        }

        self.update_anim_params(selected_ix, bounds_rc, &prev_selected, &anim_params, cx);

        let (to_left, to_width, epoch) = *anim_params.read(cx);
        if let Some(rc) = bounds_rc {
            rc.borrow_mut().placed = (to_left, to_width);
        }
        if to_width <= px(0.) {
            return None;
        }

        // The springs hold the indicator's own position and velocity, so a tab
        // switched again mid-slide is redirected from where the indicator
        // actually is rather than restarted from the tab it left.
        let indicator_key = format!("{}-tab-indicator", self.id);
        let left = spring(
            (indicator_key.clone(), "left"),
            to_left,
            cx.theme().motion_tokens().spring_move,
            window,
            cx,
        );
        let width = spring(
            (indicator_key, "width"),
            to_width,
            cx.theme().motion_tokens().spring_move,
            window,
            cx,
        );

        let variant = self.variant;
        let size = self.size;
        let inner_height = variant.inner_height(size);
        let inner_radius = variant.inner_radius(size, cx);

        let indicator = div()
            .absolute()
            .top_0()
            .bottom_0()
            .left(left)
            .w(width)
            .map(|el| match variant {
                TabVariant::Segmented => el.flex().items_center().child(
                    div()
                        .w_full()
                        .h(inner_height)
                        .bg(cx.theme().tokens.background)
                        .rounded(inner_radius)
                        .shadow(raised_shadow()),
                ),
                TabVariant::Pill => el.flex().items_center().child(
                    div()
                        .size_full()
                        .bg(cx.theme().tokens.primary)
                        .rounded(cx.theme().radius_full()),
                ),
                TabVariant::Underline => el.child(
                    div()
                        .absolute()
                        .left_0()
                        .right_0()
                        .bottom_0()
                        .h(px(2.))
                        .bg(cx.theme().tokens.primary),
                ),
                _ => el,
            });

        Some((indicator.into_any_element(), epoch))
    }

    /// Update animation parameters based on current and previous selection.
    fn update_anim_params(
        &self,
        selected_ix: usize,
        bounds_rc: &Option<Rc<RefCell<TabIndicatorBounds>>>,
        prev_selected: &gpui::Entity<usize>,
        anim_params: &gpui::Entity<(Pixels, Pixels, u64)>,
        cx: &mut App,
    ) {
        let rc = match bounds_rc {
            Some(rc) => rc,
            None => return,
        };

        let prev_ix = *prev_selected.read(cx);
        let bounds = rc.borrow();
        let container = bounds.container;

        if container.size.width == px(0.) {
            if prev_ix != selected_ix {
                prev_selected.update(cx, |v, _| *v = selected_ix);
            }
            return;
        }

        // The indicator is nested in the first tab wrapper, so its position is
        // relative to that wrapper rather than the scroll container.
        let first_tab_origin = bounds
            .tabs
            .first()
            .map(|tab| tab.origin.x)
            .unwrap_or(container.origin.x);

        if prev_ix != selected_ix {
            if let Some(to_b) = bounds.tabs.get(selected_ix) {
                let left = to_b.origin.x - first_tab_origin;
                let width = to_b.size.width;
                // Only a switch away from a tab that still exists restarts the
                // tabs' own epoch-keyed transitions.
                let epoch = anim_params.read(cx).2;
                let epoch = match bounds.tabs.get(prev_ix) {
                    Some(_) => epoch + 1,
                    None => epoch,
                };
                anim_params.update(cx, |v, _| *v = (left, width, epoch));
            }
            drop(bounds);
            prev_selected.update(cx, |v, _| *v = selected_ix);
            return;
        }

        if let Some(to_b) = bounds.tabs.get(selected_ix) {
            let left = to_b.origin.x - first_tab_origin;
            let width = to_b.size.width;
            let (to_left, to_width, epoch) = *anim_params.read(cx);

            if left != to_left || width != to_width {
                anim_params.update(cx, |v, _| *v = (left, width, epoch));
            }
        }
    }
}

impl Styled for TabBar {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Sizable for TabBar {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl RenderOnce for TabBar {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let default_gap = match self.size {
            Size::Small | Size::XSmall => px(8.),
            Size::Large => px(16.),
            _ => px(12.),
        };
        let (bg, paddings, gap): (Background, _, _) = match self.variant {
            TabVariant::Tab => {
                let padding = Edges::all(px(0.));
                (cx.theme().tokens.tab_bar.into(), padding, px(0.))
            }
            TabVariant::Outline => {
                let padding = Edges::all(px(0.));
                (cx.theme().transparent.into(), padding, default_gap)
            }
            TabVariant::Pill => {
                let padding = Edges::all(px(0.));
                (cx.theme().transparent.into(), padding, px(4.))
            }
            TabVariant::Segmented => {
                let padding_x = match self.size {
                    Size::XSmall => px(2.),
                    Size::Small => px(3.),
                    _ => px(4.),
                };
                let padding = Edges {
                    left: padding_x,
                    right: padding_x,
                    ..Default::default()
                };

                (cx.theme().tokens.tab_bar_segmented.into(), padding, px(2.))
            }
            TabVariant::Underline => {
                // This gap is same as the tab inner_paddings
                let gap = match self.size {
                    Size::XSmall => px(10.),
                    Size::Small => px(12.),
                    Size::Large => px(20.),
                    _ => px(16.),
                };

                (cx.theme().transparent.into(), Edges::all(px(0.)), gap)
            }
            TabVariant::Folder => (
                cx.theme().tokens.tab_bar.into(),
                Edges::all(px(0.)),
                FOLDER_TAB_GAP,
            ),
        };
        let overhang = self.variant.overhang(self.size, cx);
        // Inside the tabs rather than on the bar, so the bar's prefix and
        // suffix center on the full height like the tabs' content does.
        let tabs_top_padding = match self.variant {
            TabVariant::Folder => FolderTabMetrics::new(self.size, cx).top_padding,
            _ => px(0.),
        };

        let has_indicator = matches!(
            self.variant,
            TabVariant::Segmented | TabVariant::Pill | TabVariant::Underline
        );
        let num_tabs = self.children.len();

        // Bounds tracking for tab indicator animation.
        // Uses Rc<RefCell> to avoid triggering re-renders from prepaint writes.
        let bounds_rc = if has_indicator && num_tabs > 0 {
            let rc: Rc<RefCell<TabIndicatorBounds>> = window
                .use_keyed_state(format!("{}-tab-bounds", self.id), cx, |_, _| {
                    Rc::new(RefCell::new(TabIndicatorBounds::new(num_tabs)))
                })
                .read(cx)
                .clone();
            rc.borrow_mut().resize(num_tabs);
            Some(rc)
        } else {
            None
        };

        // Without a tracked handle the bar still needs one to reveal a clicked tab.
        let scroll_handle = self.scroll_handle.clone().unwrap_or_else(|| {
            window
                .use_keyed_state(format!("{}-scroll", self.id), cx, |_, _| {
                    ScrollHandle::new()
                })
                .read(cx)
                .clone()
        });
        let reveal = TabReveal {
            spring_id: format!("{}-reveal", self.id).into(),
            target: window.use_keyed_state(format!("{}-reveal", self.id), cx, |_, _| None),
            scroll_handle: scroll_handle.clone(),
            view: window.current_view(),
            peek: match self.size {
                Size::XSmall | Size::Small => px(24.),
                Size::Large => px(40.),
                _ => px(32.),
            },
            num_tabs,
        };
        reveal.advance(window, cx);

        let padding_x = paddings.left;
        let indicator = self.render_indicator(&bounds_rc, window, cx);
        let indicator_epoch = indicator.as_ref().map(|(_, epoch)| *epoch).unwrap_or(0);
        let mut indicator_element = indicator.map(|(el, _)| el);
        let indicator_ready = indicator_element.is_some();

        let has_suffix_or_menu = self.suffix.is_some() || self.menu;
        let view = window.current_view();
        let mut item_metas: Vec<(
            Option<SharedString>,
            Option<Icon>,
            bool,
            Option<TabClickHandler>,
        )> = Vec::new();
        let selected_index = self.selected_index;
        let tabs = self.base;
        let mut rendered_tabs = Vec::with_capacity(self.children.len());
        let max_width = self.max_width;
        // A hovered folder tab shows its fill and hides the separators beside
        // it, one of which belongs to its neighbor, so the bar tracks the hover.
        let hovered_tab = (self.variant == TabVariant::Folder).then(|| {
            window.use_keyed_state(format!("{}-tab-hovered", self.id), cx, |_, _| None::<usize>)
        });
        let hovered_ix = hovered_tab.as_ref().and_then(|state| *state.read(cx));
        let has_shape = |ix| selected_index == Some(ix) || hovered_ix == Some(ix);

        for (ix, child) in self.children.into_iter().enumerate() {
            item_metas.push((
                child.label.clone(),
                child.icon.clone(),
                child.disabled,
                None,
            ));
            let tab_bar_prefix = child.tab_bar_prefix.unwrap_or(true);
            let mut tab = child
                .ix(ix)
                .tab_bar_prefix(tab_bar_prefix)
                .max_width(max_width)
                .with_variant(self.variant)
                .with_size(self.size);
            tab.indicator_active = has_indicator;
            tab.indicator_ready = indicator_ready;
            tab.indicator_epoch = indicator_epoch;
            tab.hovered = hovered_ix == Some(ix);
            tab.separator = self.variant == TabVariant::Folder
                && ix + 1 < num_tabs
                && !has_shape(ix)
                && !has_shape(ix + 1);
            let disabled = tab.disabled;
            let mut tab = tab
                .when_some(selected_index, |tab, selected_index| {
                    tab.selected(selected_index == ix)
                })
                .map(|mut tab| {
                    // The bar's callback replaces the tab's own.
                    let on_click: Option<TabClickHandler> = match self.on_click.clone() {
                        Some(on_click) => {
                            Some(Rc::new(move |_, window, cx| on_click(&ix, window, cx)))
                        }
                        None => tab.on_click.take(),
                    };
                    tab.on_click = on_click.map(|on_click| {
                        let reveal = reveal.clone();
                        Rc::new(
                            move |event: &ClickEvent, window: &mut Window, cx: &mut App| {
                                reveal.reveal(ix, cx);
                                on_click(event, window, cx)
                            },
                        ) as TabClickHandler
                    });
                    tab
                });
            // The overflow menu item runs the same handler as the visible tab:
            // the bar's callback when set, otherwise the tab's own.
            if let Some(meta) = item_metas.last_mut() {
                meta.3 = tab.on_click.clone();
            }
            // The wrapper below is the flex item the bar lays out, so a tab's
            // own `flex_grow` / `flex_basis` (e.g. `flex_1()`) must size it.
            let flex_grow = tab.style().flex_grow;
            let flex_basis = tab.style().flex_basis;

            rendered_tabs.push(if let Some(ref rc) = bounds_rc {
                let rc = rc.clone();
                let selected = selected_index == Some(ix);
                // `tabs-inner` is tracked by `ScrollHandle`, which indexes its
                // direct children. Keep the indicator inside the first tab so
                // only logical tabs occupy those indices.
                div()
                    .flex_shrink_0()
                    .map(|mut this| {
                        this.style().flex_grow = flex_grow;
                        this.style().flex_basis = flex_basis;
                        this
                    })
                    .on_prepaint(move |bounds, window, _| {
                        let mut measured = rc.borrow_mut();
                        if let Some(slot) = measured.tabs.get_mut(ix) {
                            *slot = bounds;
                        }
                        // Render places the indicator from the bounds an
                        // earlier frame measured, and a view that nothing
                        // changed may not render again. When the selected tab
                        // is measured elsewhere than its indicator (on the
                        // bar's first frame above all), render the view again
                        // on the next frame. Not while the bar has no width:
                        // render leaves the indicator where it was then.
                        if selected && measured.container.size.width > px(0.) {
                            let first = measured
                                .tabs
                                .first()
                                .map_or(bounds.origin.x, |tab| tab.origin.x);
                            if (bounds.origin.x - first, bounds.size.width) != measured.placed {
                                window.on_next_frame(move |_, cx| cx.notify(view));
                            }
                        }
                    })
                    .relative()
                    .when(ix == 0, |this| {
                        this.when_some(indicator_element.take(), |this, indicator| {
                            this.child(indicator)
                        })
                    })
                    .child(tab)
                    .into_any_element()
            } else if let Some(hovered_tab) = hovered_tab.clone() {
                div()
                    .id(("folder-tab", ix))
                    .flex_shrink_0()
                    .map(|mut this| {
                        this.style().flex_grow = flex_grow;
                        this.style().flex_basis = flex_basis;
                        this
                    })
                    .when(!disabled, |this| {
                        this.on_hover(move |hovered, _, cx| {
                            hovered_tab.update(cx, |state, cx| {
                                let next = match *hovered {
                                    true => Some(ix),
                                    false if *state == Some(ix) => None,
                                    false => *state,
                                };
                                if next != *state {
                                    *state = next;
                                    cx.notify();
                                }
                            });
                        })
                    })
                    .child(tab)
                    .into_any_element()
            } else {
                tab.into_any_element()
            });
        }

        tabs.group("tab-bar")
            .relative()
            .flex()
            .items_center()
            .bg(bg)
            .text_color(cx.theme().tab_foreground)
            .when(
                self.variant == TabVariant::Underline || self.variant == TabVariant::Tab,
                |this| {
                    this.child(
                        div()
                            .id("border-b")
                            .absolute()
                            .left_0()
                            .bottom_0()
                            .size_full()
                            .border_b_1()
                            .border_color(cx.theme().border),
                    )
                },
            )
            .rounded(self.variant.tab_bar_radius(self.size, cx))
            .paddings(paddings)
            .refine_style(&self.style)
            .when_some(self.prefix, |this, prefix| this.child(prefix))
            .child(
                h_flex()
                    .id("tabs")
                    .flex_1()
                    .min_w_0()
                    .mx(-padding_x)
                    .px(padding_x)
                    .overflow_x_hidden()
                    // `on_prepaint` adds a canvas child. Keep that helper on
                    // the non-scrolling wrapper so it cannot shift tab indices.
                    .when_some(bounds_rc.clone(), |this, rc| {
                        this.on_prepaint(move |bounds, _, _| {
                            rc.borrow_mut().container = bounds;
                        })
                    })
                    .child(
                        h_flex()
                            .id("tabs-inner")
                            // Fill the bar so tabs can grow into the free space;
                            // as a scroll container it still shrinks below its content.
                            .flex_1()
                            // Keep the scroll viewport inside the wrapper padding so
                            // explicit reveals leave space at both ends of the bar.
                            .relative()
                            // Room for the end tabs' curves inside the viewport.
                            .px(overhang)
                            .pt(tabs_top_padding)
                            .gap(gap)
                            .overflow_x_scroll()
                            .lock_scroll_axis()
                            .track_scroll(&scroll_handle)
                            .children(rendered_tabs)
                            .when(has_suffix_or_menu, |this| this.child(self.last_empty_space)),
                    )
                    // Outside the tracked children so tab indices stay unchanged.
                    .child(ScrollableMask::vertical_wheel(&scroll_handle)),
            )
            .when(self.menu, |this| {
                this.child(
                    Button::new("more")
                        .xsmall()
                        .ghost()
                        .dropdown_caret(true)
                        .dropdown_menu(move |mut this, _, _| {
                            this = this.scrollable(true);
                            for (ix, (label, icon, disabled, on_click)) in
                                item_metas.iter().enumerate()
                            {
                                let base = if let Some(label) = label.clone() {
                                    PopupMenuItem::new(label)
                                } else if let Some(icon) = icon.clone() {
                                    PopupMenuItem::element(move |_, _| icon.clone())
                                } else {
                                    PopupMenuItem::new(t!("Dock.Unnamed"))
                                };
                                this = this.item(
                                    base.checked(selected_index == Some(ix))
                                        .disabled(*disabled)
                                        .when_some(on_click.clone(), |this, on_click| {
                                            this.on_click(move |event, window, cx| {
                                                on_click(event, window, cx)
                                            })
                                        }),
                                );
                            }

                            this
                        })
                        .anchor(Anchor::TopRight),
                )
            })
            .when_some(self.suffix, |this, suffix| this.child(suffix))
    }
}

type TabClickHandler = Rc<dyn Fn(&ClickEvent, &mut Window, &mut App) + 'static>;

/// Scrolls a clicked tab into view, the way an `NSScrollView` reveals a
/// clicked row, and leaves part of the tab beyond it showing so the strip
/// visibly continues. Only a click starts this; selection, tab and layout
/// changes leave the offset where the user put it.
#[derive(Clone)]
struct TabReveal {
    spring_id: SharedString,
    /// The offset a reveal is travelling to, while one is.
    target: Entity<Option<RevealTarget>>,
    scroll_handle: ScrollHandle,
    view: EntityId,
    /// How much of the neighbouring tab stays visible.
    peek: Pixels,
    num_tabs: usize,
}

#[derive(Clone, Copy)]
struct RevealTarget {
    to: Pixels,
    /// The offset the previous frame set, `None` before the first frame.
    last: Option<Pixels>,
}

impl TabReveal {
    fn reveal(&self, ix: usize, cx: &mut App) {
        let Some(to) = self.offset_revealing(ix) else {
            return;
        };
        let running = self.target.read(cx).is_some();
        if !running && to == self.scroll_handle.offset().x {
            return;
        }
        self.target.update(cx, |target, _| match target {
            // Retargeting keeps the spring's velocity.
            Some(target) => target.to = to,
            None => *target = Some(RevealTarget { to, last: None }),
        });
        cx.notify(self.view);
    }

    /// The horizontal offset that shows tab `ix` and `peek` of each neighbour,
    /// moving as little as possible. The tab itself wins on a narrow bar.
    fn offset_revealing(&self, ix: usize) -> Option<Pixels> {
        let handle = &self.scroll_handle;
        let viewport = handle.bounds();
        let tab = handle.bounds_for_item(ix)?;
        let max = handle.max_offset().x;
        // Child bounds are laid out unscrolled: content at x is on screen at
        // x + offset, so the visible content spans `viewport - offset`.
        let want_left = match ix.checked_sub(1).and_then(|ix| handle.bounds_for_item(ix)) {
            Some(prev) => (prev.right() - self.peek).max(prev.left()),
            None => viewport.left(),
        };
        let want_right = match (ix + 1 < self.num_tabs)
            .then(|| handle.bounds_for_item(ix + 1))
            .flatten()
        {
            Some(next) => (next.left() + self.peek).min(next.right()),
            None => viewport.right() + max,
        };

        let mut offset = handle.offset().x;
        let show_left = |offset: &mut Pixels, left: Pixels| {
            if left < viewport.left() - *offset {
                *offset = viewport.left() - left;
            }
        };
        let show_right = |offset: &mut Pixels, right: Pixels| {
            if right > viewport.right() - *offset {
                *offset = viewport.right() - right;
            }
        };
        // Whichever is applied last wins: the neighbour the click heads
        // toward over the one behind it, and the tab over both.
        if tab.center().x + offset > viewport.center().x {
            show_left(&mut offset, want_left);
            show_right(&mut offset, want_right);
        } else {
            show_right(&mut offset, want_right);
            show_left(&mut offset, want_left);
        }
        show_right(&mut offset, tab.right());
        show_left(&mut offset, tab.left());
        Some(offset.min(px(0.)).max(-max))
    }

    /// Steps a running reveal by one frame.
    fn advance(&self, window: &mut Window, cx: &mut App) {
        let Some(target) = *self.target.read(cx) else {
            return;
        };
        let offset = self.scroll_handle.offset();
        // A wheel or trackpad scroll since the last frame hands the strip back.
        if target.last.is_some_and(|last| last != offset.x) {
            self.target.update(cx, |target, _| *target = None);
            return;
        }

        let policy = cx.theme().motion_tokens().spring_move;
        if target.last.is_none() {
            // Start from where the strip is, not where a previous reveal ended.
            spring(
                self.spring_id.clone(),
                offset.x,
                policy.with_travel(false),
                window,
                cx,
            );
        }
        let x = spring(self.spring_id.clone(), target.to, policy, window, cx);
        self.scroll_handle.set_offset(point(x, offset.y));
        self.target.update(cx, |state, _| {
            *state = (x != target.to).then_some(RevealTarget {
                last: Some(x),
                ..target
            })
        });
    }
}

#[cfg(test)]
mod tests {
    use std::{
        cell::{Cell, RefCell},
        rc::Rc,
    };

    use gpui::{Context, Modifiers, MouseButton, MouseUpEvent, Render, TestAppContext};

    use super::*;
    use crate::scroll::ScrollableElement as _;

    struct Harness {
        group_handler: bool,
        disabled: bool,
        child_clicks: Rc<Cell<usize>>,
        group_clicks: Rc<Cell<usize>>,
    }

    impl Render for Harness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let child_clicks = self.child_clicks.clone();
            let group_clicks = self.group_clicks.clone();
            TabBar::new("tabs")
                .w(px(240.))
                .child(
                    Tab::new()
                        .debug_selector(|| "first-tab".into())
                        .disabled(self.disabled)
                        .label("First")
                        .on_click(move |_, _, _| child_clicks.set(child_clicks.get() + 1)),
                )
                .when(self.group_handler, |tabs| {
                    tabs.on_click(move |ix, _, _| group_clicks.set(*ix + 1))
                })
        }
    }

    fn harness(
        cx: &mut TestAppContext,
        group_handler: bool,
        disabled: bool,
    ) -> (
        &mut gpui::VisualTestContext,
        Rc<Cell<usize>>,
        Rc<Cell<usize>>,
    ) {
        cx.update(crate::theme::init);
        let child_clicks = Rc::new(Cell::new(0));
        let group_clicks = Rc::new(Cell::new(0));
        let (_, cx) = cx.add_window_view({
            let child_clicks = child_clicks.clone();
            let group_clicks = group_clicks.clone();
            move |_, _| Harness {
                group_handler,
                disabled,
                child_clicks,
                group_clicks,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        (cx, child_clicks, group_clicks)
    }

    #[gpui::test]
    fn group_callback_overrides_child_callback(cx: &mut TestAppContext) {
        let (cx, child_clicks, group_clicks) = harness(cx, true, false);
        let position = cx.debug_bounds("first-tab").unwrap().center();
        cx.simulate_click(position, Modifiers::default());
        assert_eq!(child_clicks.get(), 0);
        assert_eq!(group_clicks.get(), 1);
    }

    #[gpui::test]
    fn child_callback_is_preserved_without_group_callback(cx: &mut TestAppContext) {
        let (cx, child_clicks, group_clicks) = harness(cx, false, false);
        let position = cx.debug_bounds("first-tab").unwrap().center();
        cx.simulate_click(position, Modifiers::default());
        assert_eq!(child_clicks.get(), 1);
        assert_eq!(group_clicks.get(), 0);
    }

    #[gpui::test]
    fn disabled_tab_suppresses_child_and_group_callbacks(cx: &mut TestAppContext) {
        let (cx, child_clicks, group_clicks) = harness(cx, true, true);
        let position = cx.debug_bounds("first-tab").unwrap().center();
        cx.simulate_click(position, Modifiers::default());
        assert_eq!(child_clicks.get(), 0);
        assert_eq!(group_clicks.get(), 0);
    }

    struct MenuHarness {
        group_handler: bool,
        clicks: Rc<RefCell<Vec<String>>>,
        events: Rc<RefCell<Vec<ClickEvent>>>,
    }

    impl Render for MenuHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            let events = self.events.clone();
            let tab = |label: &'static str, clicks: Rc<RefCell<Vec<String>>>| {
                let events = events.clone();
                Tab::new()
                    .debug_selector(move || format!("{label}-tab"))
                    .label(label)
                    .on_click(move |event, _, _| {
                        clicks.borrow_mut().push(format!("tab {label}"));
                        events.borrow_mut().push(event.clone());
                    })
            };
            let clicks = self.clicks.clone();
            div().size_full().child(
                TabBar::new("menu-tabs")
                    .w(px(240.))
                    .menu(true)
                    .child(tab("First", self.clicks.clone()))
                    .child(tab("Second", self.clicks.clone()))
                    .when(self.group_handler, |tabs| {
                        tabs.on_click(move |ix, _, _| clicks.borrow_mut().push(format!("bar {ix}")))
                    }),
            )
        }
    }

    /// Opens the overflow menu and activates its first item.
    fn choose_first_menu_item(
        group_handler: bool,
        activate: impl FnOnce(&mut gpui::VisualTestContext),
        cx: &mut TestAppContext,
    ) -> (Vec<String>, Vec<ClickEvent>) {
        cx.update(crate::init);
        let clicks = Rc::new(RefCell::new(Vec::new()));
        let events = Rc::new(RefCell::new(Vec::new()));
        let (_, cx) = cx.add_window_view({
            let clicks = clicks.clone();
            let events = events.clone();
            move |_, _| MenuHarness {
                group_handler,
                clicks,
                events,
            }
        });
        cx.update(|window, cx| window.draw(cx).clear(cx));
        let tab = cx.debug_bounds("First-tab").unwrap();
        // The menu button is the last thing in the 240px bar.
        let more = point(px(232.), tab.center().y);
        cx.simulate_mouse_down(more, MouseButton::Left, Modifiers::default());
        cx.simulate_event(MouseUpEvent {
            position: more,
            button: MouseButton::Left,
            modifiers: Modifiers::default(),
            click_count: 1,
        });
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
        activate(cx);
        cx.run_until_parked();
        (clicks.borrow().clone(), events.borrow().clone())
    }

    #[gpui::test]
    fn overflow_menu_runs_the_tab_callback_without_a_bar_callback(cx: &mut TestAppContext) {
        assert_eq!(
            choose_first_menu_item(false, |cx| cx.simulate_keystrokes("down enter"), cx).0,
            vec!["tab First".to_string()]
        );
    }

    #[gpui::test]
    fn overflow_menu_prefers_the_bar_callback(cx: &mut TestAppContext) {
        assert_eq!(
            choose_first_menu_item(true, |cx| cx.simulate_keystrokes("down enter"), cx).0,
            vec!["bar 0".to_string()]
        );
    }

    #[cfg(feature = "test-support")]
    #[gpui::test]
    fn overflow_menu_preserves_pointer_events_and_keyboard_activation(cx: &mut TestAppContext) {
        let position = Cell::new(point(px(0.), px(0.)));
        let (clicks, events) = choose_first_menu_item(
            false,
            |cx| {
                let item = cx.update(|window, _| {
                    gpui_base::test_support::find_all(window, &[], &ElementId::from(0usize))
                        .into_iter()
                        .find(|item| item.role() == Some(gpui::Role::MenuItem))
                        .expect("first overflow menu item")
                });
                position.set(item.bounds().center());
                cx.simulate_click(
                    position.get(),
                    Modifiers {
                        shift: true,
                        ..Modifiers::default()
                    },
                );
            },
            cx,
        );
        assert_eq!(clicks, vec!["tab First"]);
        assert_eq!(events.len(), 1);
        assert!(matches!(events[0], ClickEvent::Mouse(_)));
        assert!(events[0].modifiers().shift);
        assert_eq!(events[0].mouse_position(), Some(position.get()));

        let (clicks, events) =
            choose_first_menu_item(false, |cx| cx.simulate_keystrokes("down enter"), cx);
        assert_eq!(clicks, vec!["tab First"]);
        assert_eq!(events.len(), 1);
        assert!(matches!(events[0], ClickEvent::Keyboard(_)));
    }

    struct ContentHarness;

    impl Render for ContentHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            TabBar::new("content-tabs").w(px(320.)).child(
                Tab::new()
                    .prefix(div().debug_selector(|| "tab-prefix".into()).child("P"))
                    .child(div().debug_selector(|| "tab-child".into()).child("Content"))
                    .suffix(div().debug_selector(|| "tab-suffix".into()).child("S")),
            )
        }
    }

    #[gpui::test]
    fn prefix_content_and_suffix_keep_their_order(cx: &mut TestAppContext) {
        cx.update(crate::theme::init);
        let (_, cx) = cx.add_window_view(|_, _| ContentHarness);
        cx.update(|window, cx| window.draw(cx).clear(cx));

        let prefix = cx.debug_bounds("tab-prefix").unwrap();
        let child = cx.debug_bounds("tab-child").unwrap();
        let suffix = cx.debug_bounds("tab-suffix").unwrap();
        assert!(prefix.origin.x < child.origin.x);
        assert!(child.origin.x < suffix.origin.x);
        assert!(prefix.size.width > px(0.));
        assert!(child.size.width > px(0.));
        assert!(suffix.size.width > px(0.));
    }

    struct ScrollHarness {
        scroll_handle: ScrollHandle,
    }

    struct DynamicScrollHarness {
        scroll_handle: ScrollHandle,
        menu: bool,
        size: Size,
        tabs: usize,
        selected_index: usize,
    }

    struct ManualScrollHarness {
        scroll_handle: ScrollHandle,
        tabs: usize,
        selected_index: usize,
        label: &'static str,
        top: Pixels,
    }

    impl ScrollHarness {
        fn tabs() -> impl Iterator<Item = Tab> {
            (0..5).map(|ix| {
                Tab::new()
                    .w(px(60.))
                    .label(format!("Tab {ix}"))
                    .debug_selector(move || format!("tab-{ix}"))
            })
        }
    }

    impl Render for ScrollHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().w(px(100.)).child(
                TabBar::new("scrolling-tabs")
                    .w_full()
                    .segmented()
                    .menu(true)
                    .track_scroll(&self.scroll_handle)
                    .selected_index(4)
                    .children(Self::tabs()),
            )
        }
    }

    impl DynamicScrollHarness {
        fn tabs(&self) -> impl Iterator<Item = Tab> {
            (0..self.tabs).map(|ix| {
                Tab::new()
                    .w(px(60.))
                    .label(format!("Tab {ix}"))
                    .debug_selector(move || format!("dynamic-tab-{ix}"))
            })
        }
    }

    impl Render for DynamicScrollHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .w(px(100.))
                .debug_selector(|| "dynamic-bar".into())
                .child(
                    TabBar::new("dynamic-scrolling-tabs")
                        .with_size(self.size)
                        .w_full()
                        .segmented()
                        .menu(self.menu)
                        .track_scroll(&self.scroll_handle)
                        .selected_index(self.selected_index)
                        .children(self.tabs()),
                )
        }
    }

    impl ManualScrollHarness {
        fn tabs(&self) -> impl Iterator<Item = Tab> {
            let width = if self.label == "old" {
                px(60.)
            } else {
                px(120.)
            };
            let label = self.label;
            (0..self.tabs).map(move |ix| {
                Tab::new()
                    .w(width)
                    .label(format!("Tab {ix} {label}"))
                    .debug_selector(move || format!("manual-tab-{ix}"))
            })
        }
    }

    impl Render for ManualScrollHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div().w(px(160.)).h(px(40.)).child(
                div().relative().top(self.top).w_full().child(
                    TabBar::new("manual-scrolling-tabs")
                        .w_full()
                        .segmented()
                        .menu(true)
                        .track_scroll(&self.scroll_handle)
                        .selected_index(self.selected_index)
                        .children(self.tabs()),
                ),
            )
        }
    }

    fn draw(cx: &mut gpui::VisualTestContext) {
        cx.run_until_parked();
        cx.update(|window, cx| window.draw(cx).clear(cx));
    }

    #[gpui::test]
    fn scrolling_to_a_tab_uses_logical_tab_indices(cx: &mut TestAppContext) {
        cx.update(crate::theme::init);
        let scroll_handle = ScrollHandle::new();
        let (_, cx) = cx.add_window_view({
            let scroll_handle = scroll_handle.clone();
            move |_, _| ScrollHarness { scroll_handle }
        });

        draw(cx);
        draw(cx);
        assert_eq!(scroll_handle.offset().x, px(0.));
        scroll_handle.scroll_to_item(4);
        draw(cx);
        draw(cx);

        let viewport = scroll_handle.bounds();
        let last_tab = cx.debug_bounds("tab-4").unwrap();
        assert!(
            last_tab.left() >= viewport.left(),
            "last tab {last_tab:?} is left of viewport {viewport:?}, offset {:?}",
            scroll_handle.offset()
        );
        assert!(
            last_tab.right() <= viewport.right(),
            "last tab {last_tab:?} is right of viewport {viewport:?}, offset {:?}",
            scroll_handle.offset()
        );
        assert_eq!(scroll_handle.children_count(), 6);
    }

    #[gpui::test]
    fn scrolling_to_a_new_tab_preserves_the_explicit_target(cx: &mut TestAppContext) {
        cx.update(crate::theme::init);
        let scroll_handle = ScrollHandle::new();
        let (view, cx) = cx.add_window_view({
            let scroll_handle = scroll_handle.clone();
            move |_, _| DynamicScrollHarness {
                scroll_handle,
                menu: true,
                size: Size::default(),
                tabs: 4,
                selected_index: 3,
            }
        });

        draw(cx);
        draw(cx);

        view.update(cx, |view, cx| {
            view.tabs = 5;
            view.selected_index = 4;
            view.scroll_handle.scroll_to_item(4);
            cx.notify();
        });
        draw(cx);

        let viewport = scroll_handle.bounds();
        let last_tab = cx.debug_bounds("dynamic-tab-4").unwrap();
        assert!(last_tab.left() >= viewport.left());
        assert!(last_tab.right() <= viewport.right());
        assert_eq!(scroll_handle.children_count(), 6);
    }

    #[gpui::test]
    fn scrolling_to_a_new_tab_preserves_bar_padding(cx: &mut TestAppContext) {
        cx.update(crate::theme::init);
        for (size, padding) in [
            (Size::XSmall, px(2.)),
            (Size::Small, px(3.)),
            (Size::Medium, px(4.)),
            (Size::Large, px(4.)),
        ] {
            let scroll_handle = ScrollHandle::new();
            let (view, cx) = cx.add_window_view({
                let scroll_handle = scroll_handle.clone();
                move |_, _| DynamicScrollHarness {
                    scroll_handle,
                    menu: false,
                    size,
                    tabs: 4,
                    selected_index: 0,
                }
            });
            draw(cx);
            draw(cx);
            view.update(cx, |view, cx| {
                view.tabs = 5;
                view.scroll_handle.scroll_to_item(4);
                cx.notify();
            });
            draw(cx);
            draw(cx);
            let bar = cx.debug_bounds("dynamic-bar").unwrap();
            let last_tab = cx.debug_bounds("dynamic-tab-4").unwrap();
            assert_eq!(
                bar.right() - last_tab.right(),
                padding,
                "right padding for {size:?}"
            );
            scroll_handle.scroll_to_item(0);
            draw(cx);
            draw(cx);
            let first_tab = cx.debug_bounds("dynamic-tab-0").unwrap();
            assert_eq!(
                first_tab.left() - bar.left(),
                padding,
                "left padding for {size:?}"
            );
            assert_eq!(scroll_handle.children_count(), 5);
        }
    }

    #[gpui::test]
    fn closing_an_unselected_trailing_tab_preserves_manual_scrolling(cx: &mut TestAppContext) {
        cx.update(crate::theme::init);
        let scroll_handle = ScrollHandle::new();
        let (view, cx) = cx.add_window_view({
            let scroll_handle = scroll_handle.clone();
            move |_, _| ManualScrollHarness {
                scroll_handle,
                tabs: 6,
                selected_index: 0,
                label: "old",
                top: px(0.),
            }
        });

        draw(cx);
        scroll_handle.set_offset(gpui::point(px(-100.), px(0.)));
        draw(cx);
        assert_eq!(scroll_handle.offset().x, px(-100.));

        view.update(cx, |view, cx| {
            view.tabs = 5;
            cx.notify();
        });
        draw(cx);

        assert_eq!(scroll_handle.offset().x, px(-100.));
    }

    #[gpui::test]
    fn changing_selection_does_not_move_manual_scrolling(cx: &mut TestAppContext) {
        cx.update(crate::theme::init);
        let scroll_handle = ScrollHandle::new();
        let (view, cx) = cx.add_window_view({
            let scroll_handle = scroll_handle.clone();
            move |_, _| ManualScrollHarness {
                scroll_handle,
                tabs: 6,
                selected_index: 0,
                label: "old",
                top: px(0.),
            }
        });

        draw(cx);
        scroll_handle.set_offset(gpui::point(px(-100.), px(0.)));
        draw(cx);

        view.update(cx, |view, cx| {
            view.selected_index = 5;
            cx.notify();
        });
        draw(cx);

        assert_eq!(scroll_handle.offset().x, px(-100.));
    }

    #[gpui::test]
    fn changing_tab_labels_does_not_move_manual_scrolling(cx: &mut TestAppContext) {
        cx.update(crate::theme::init);
        let scroll_handle = ScrollHandle::new();
        let (view, cx) = cx.add_window_view({
            let scroll_handle = scroll_handle.clone();
            move |_, _| ManualScrollHarness {
                scroll_handle,
                tabs: 6,
                selected_index: 0,
                label: "old",
                top: px(0.),
            }
        });

        draw(cx);
        scroll_handle.set_offset(gpui::point(px(-100.), px(0.)));
        draw(cx);

        view.update(cx, |view, cx| {
            view.label = "new";
            cx.notify();
        });
        draw(cx);

        assert_eq!(scroll_handle.offset().x, px(-100.));
    }

    #[gpui::test]
    fn moving_the_tab_bar_preserves_manual_scrolling(cx: &mut TestAppContext) {
        cx.update(crate::theme::init);
        let scroll_handle = ScrollHandle::new();
        let (view, cx) = cx.add_window_view({
            let scroll_handle = scroll_handle.clone();
            move |_, _| ManualScrollHarness {
                scroll_handle,
                tabs: 6,
                selected_index: 0,
                label: "old",
                top: px(0.),
            }
        });

        draw(cx);
        scroll_handle.set_offset(gpui::point(px(-100.), px(0.)));
        draw(cx);
        assert_eq!(scroll_handle.offset().x, px(-100.));
        let viewport_size = scroll_handle.bounds().size;

        view.update(cx, |view, cx| {
            view.top = px(20.);
            cx.notify();
        });
        draw(cx);

        assert_eq!(scroll_handle.bounds().size, viewport_size);
        assert_eq!(scroll_handle.offset().x, px(-100.));
    }

    struct FlexHarness {
        variant: TabVariant,
    }

    impl Render for FlexHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .w(px(200.))
                .debug_selector(|| "flex-bar".into())
                .child(
                    TabBar::new("flex-tabs")
                        .w_full()
                        .with_variant(self.variant)
                        .selected_index(0)
                        .child(
                            Tab::new()
                                .flex_1()
                                .label("A")
                                .debug_selector(|| "flex-tab-0".into()),
                        )
                        .child(
                            Tab::new()
                                .flex_1()
                                .label("B")
                                .debug_selector(|| "flex-tab-1".into()),
                        ),
                )
        }
    }

    #[gpui::test]
    fn flex_tabs_share_the_available_width(cx: &mut TestAppContext) {
        cx.update(crate::theme::init);
        for variant in [
            TabVariant::Tab,
            TabVariant::Outline,
            TabVariant::Segmented,
            TabVariant::Pill,
            TabVariant::Underline,
        ] {
            let (_, cx) = cx.add_window_view(move |_, _| FlexHarness { variant });
            draw(cx);
            draw(cx);

            let bar = cx.debug_bounds("flex-bar").unwrap();
            let first = cx.debug_bounds("flex-tab-0").unwrap();
            let second = cx.debug_bounds("flex-tab-1").unwrap();
            assert_eq!(first.size.width, second.size.width, "{variant:?}");
            // Only the bar's own padding may remain on either side.
            assert_eq!(
                first.left() - bar.left(),
                bar.right() - second.right(),
                "{variant:?}"
            );
            assert!(
                bar.right() - second.right() <= px(4.),
                "{variant:?}: tabs end at {:?} but the bar ends at {:?}",
                second.right(),
                bar.right()
            );
        }
    }

    struct ClickRevealHarness {
        group_handler: bool,
        scroll_handle: Option<ScrollHandle>,
    }

    impl Render for ClickRevealHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            // Neither callback notifies.
            div()
                .w(px(100.))
                .debug_selector(|| "click-bar".into())
                .child(
                    TabBar::new("click-reveal-tabs")
                        .w_full()
                        .when_some(self.scroll_handle.as_ref(), |tabs, handle| {
                            tabs.track_scroll(handle)
                        })
                        .children((0..5).map(|ix| {
                            Tab::new()
                                .w(px(60.))
                                .label(format!("Tab {ix}"))
                                .debug_selector(move || format!("click-tab-{ix}"))
                                .on_click(|_, _, _| {})
                        }))
                        .when(self.group_handler, |tabs| tabs.on_click(|_, _, _| {})),
                )
        }
    }

    fn click_reveal_harness(
        cx: &mut TestAppContext,
        group_handler: bool,
        scroll_handle: Option<ScrollHandle>,
        reduce_motion: bool,
    ) -> &mut gpui::VisualTestContext {
        cx.update(|cx| {
            crate::theme::init(cx);
            cx.set_reduce_motion(reduce_motion);
        });
        let (_, cx) = cx.add_window_view(move |_, _| ClickRevealHarness {
            group_handler,
            scroll_handle,
        });
        draw(cx);
        cx
    }

    fn next_frame(cx: &mut gpui::VisualTestContext) {
        cx.executor()
            .advance_clock(std::time::Duration::from_millis(16));
        cx.update(|window, cx| window.simulate_next_frame(cx));
        draw(cx);
    }

    #[gpui::test]
    fn clicking_a_clipped_tab_reveals_it_and_part_of_the_next(cx: &mut TestAppContext) {
        for group_handler in [false, true] {
            let cx = click_reveal_harness(cx, group_handler, None, true);
            let bar = cx.debug_bounds("click-bar").unwrap();
            let tab = cx.debug_bounds("click-tab-1").unwrap();
            assert!(tab.right() > bar.right(), "tab 1 starts clipped");

            cx.simulate_click(tab.center(), Modifiers::default());
            draw(cx);

            let tab = cx.debug_bounds("click-tab-1").unwrap();
            let next = cx.debug_bounds("click-tab-2").unwrap();
            assert!(tab.left() >= bar.left() && tab.right() <= bar.right());
            assert_eq!(bar.right() - next.left(), px(32.), "group: {group_handler}");
        }
    }

    #[gpui::test]
    fn clicking_the_last_tab_reveals_the_end_of_the_bar(cx: &mut TestAppContext) {
        let scroll_handle = ScrollHandle::new();
        let cx = click_reveal_harness(cx, true, Some(scroll_handle.clone()), true);
        scroll_handle.set_offset(gpui::point(px(-160.), px(0.)));
        draw(cx);

        let tab = cx.debug_bounds("click-tab-4").unwrap();
        cx.simulate_click(
            tab.origin + gpui::point(px(10.), px(10.)),
            Modifiers::default(),
        );
        draw(cx);

        assert_eq!(scroll_handle.offset().x, -scroll_handle.max_offset().x);
    }

    #[gpui::test]
    fn reveal_animates_and_yields_to_manual_scrolling(cx: &mut TestAppContext) {
        let scroll_handle = ScrollHandle::new();
        let cx = click_reveal_harness(cx, true, Some(scroll_handle.clone()), false);

        let tab = cx.debug_bounds("click-tab-1").unwrap();
        cx.simulate_click(tab.center(), Modifiers::default());
        draw(cx);
        next_frame(cx);
        let moving = scroll_handle.offset().x;
        assert!(
            moving < px(0.) && moving > px(-52.),
            "mid-flight at {moving:?}"
        );

        // The user scrolls while the reveal is still travelling.
        wheel(
            cx,
            scroll_handle.bounds().center(),
            gpui::ScrollDelta::Lines(point(0., 1.)),
            gpui::TouchPhase::Moved,
        );
        let manual = scroll_handle.offset().x;
        assert!(manual > moving);
        let after_wheel = cx.debug_bounds("click-tab-1").unwrap();
        for _ in 0..30 {
            next_frame(cx);
        }
        assert_eq!(scroll_handle.offset().x, manual);
        assert_eq!(cx.debug_bounds("click-tab-1").unwrap(), after_wheel);

        // A new click travels all the way.
        cx.simulate_click(
            tab.center() - gpui::point(px(10.), px(0.)),
            Modifiers::default(),
        );
        for _ in 0..60 {
            next_frame(cx);
        }
        assert_eq!(scroll_handle.offset().x, px(-52.));
    }

    struct WheelHarness {
        scroll_handle: Option<ScrollHandle>,
        variant: TabVariant,
    }

    fn wheel_tabs(handle: Option<&ScrollHandle>, variant: TabVariant, tabs: usize) -> TabBar {
        TabBar::new("wheel-tabs")
            .w_full()
            .with_variant(variant)
            .when_some(handle, |tabs, handle| tabs.track_scroll(handle))
            .children((0..tabs).map(|ix| {
                Tab::new()
                    .w(px(60.))
                    .label(format!("Tab {ix}"))
                    .debug_selector(move || format!("wheel-tab-{ix}"))
            }))
    }

    impl Render for WheelHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .w(px(160.))
                .debug_selector(|| "wheel-bar".into())
                .child(wheel_tabs(self.scroll_handle.as_ref(), self.variant, 6))
        }
    }

    fn wheel(
        cx: &mut gpui::VisualTestContext,
        position: gpui::Point<Pixels>,
        delta: gpui::ScrollDelta,
        touch_phase: gpui::TouchPhase,
    ) {
        cx.simulate_event(gpui::ScrollEvent {
            position,
            delta,
            touch_phase,
            ..Default::default()
        });
        draw(cx);
    }

    #[gpui::test]
    fn vertical_mouse_wheel_scrolls_each_variant_with_and_without_a_tracked_handle(
        cx: &mut TestAppContext,
    ) {
        cx.update(crate::theme::init);
        for variant in [
            TabVariant::Tab,
            TabVariant::Outline,
            TabVariant::Segmented,
            TabVariant::Pill,
            TabVariant::Underline,
            TabVariant::Folder,
        ] {
            for tracked in [false, true] {
                let scroll_handle = tracked.then(ScrollHandle::new);
                let (_, cx) = cx.add_window_view({
                    let scroll_handle = scroll_handle.clone();
                    move |_, _| WheelHarness {
                        scroll_handle,
                        variant,
                    }
                });
                draw(cx);
                draw(cx);
                let bar = cx.debug_bounds("wheel-bar").unwrap();
                let first_before = cx.debug_bounds("wheel-tab-0").unwrap();
                let last_before = cx.debug_bounds("wheel-tab-5").unwrap();
                assert!(
                    last_before.left() > bar.right(),
                    "{variant:?}, tracked: {tracked}"
                );

                wheel(
                    cx,
                    first_before.center(),
                    gpui::ScrollDelta::Lines(point(0., -100.)),
                    gpui::TouchPhase::Moved,
                );
                let first_after = cx.debug_bounds("wheel-tab-0").unwrap();
                let last_after = cx.debug_bounds("wheel-tab-5").unwrap();
                assert!(
                    first_after.left() < first_before.left(),
                    "{variant:?}, tracked: {tracked}, bar {bar:?}, first {first_before:?}, after {first_after:?}"
                );
                assert!(last_after.left() >= bar.left() && last_after.right() <= bar.right());
                if let Some(handle) = &scroll_handle {
                    assert_eq!(handle.offset().x, -handle.max_offset().x);
                    assert_eq!(handle.offset().y, px(0.));
                }

                wheel(
                    cx,
                    first_before.center(),
                    gpui::ScrollDelta::Lines(point(0., 100.)),
                    gpui::TouchPhase::Moved,
                );
                assert_eq!(cx.debug_bounds("wheel-tab-0").unwrap(), first_before);
                if let Some(handle) = &scroll_handle {
                    assert_eq!(handle.offset(), point(px(0.), px(0.)));
                }
            }
        }
    }

    #[derive(Clone)]
    enum WheelParent {
        Div(ScrollHandle),
        List(gpui::ListState),
        Scrollable,
    }

    impl WheelParent {
        fn offset(&self) -> Option<(usize, Pixels)> {
            match self {
                Self::Div(handle) => Some((0, -handle.offset().y)),
                Self::List(state) => {
                    let offset = state.logical_scroll_top();
                    Some((offset.item_ix, offset.offset_in_item))
                }
                // Component Scrollable keeps its viewport handle private. Its
                // actual movement is checked through the tab's rendered Y bound.
                Self::Scrollable => None,
            }
        }
    }

    struct NestedWheelHarness {
        parent: WheelParent,
        scroll_handle: ScrollHandle,
        tabs: usize,
    }

    impl Render for NestedWheelHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            match &self.parent {
                WheelParent::Div(parent) => crate::v_flex()
                    .id("wheel-parent")
                    .w(px(160.))
                    .h(px(100.))
                    .overflow_y_scroll()
                    .lock_scroll_axis()
                    .track_scroll(parent)
                    .child(div().w_full().h(px(60.)).flex_shrink_0().child(wheel_tabs(
                        Some(&self.scroll_handle),
                        TabVariant::Tab,
                        self.tabs,
                    )))
                    .child(div().h(px(400.)).flex_shrink_0())
                    .into_any_element(),
                WheelParent::Scrollable => crate::v_flex()
                    .w(px(160.))
                    .h(px(100.))
                    .child(div().w_full().h(px(60.)).flex_shrink_0().child(wheel_tabs(
                        Some(&self.scroll_handle),
                        TabVariant::Tab,
                        self.tabs,
                    )))
                    .child(div().h(px(400.)).flex_shrink_0())
                    .overflow_y_scrollbar()
                    .into_any_element(),
                WheelParent::List(parent) => {
                    let handle = self.scroll_handle.clone();
                    let tabs = self.tabs;
                    div()
                        .w(px(160.))
                        .h(px(100.))
                        .child(
                            gpui::list(parent.clone(), move |ix, _, _| {
                                if ix == 0 {
                                    div()
                                        .w_full()
                                        .h(px(60.))
                                        .child(wheel_tabs(Some(&handle), TabVariant::Tab, tabs))
                                        .into_any_element()
                                } else {
                                    div().w_full().h(px(40.)).into_any_element()
                                }
                            })
                            .w_full()
                            .h_full(),
                        )
                        .into_any_element()
                }
            }
        }
    }

    #[gpui::test]
    fn vertical_mouse_wheel_uses_tabs_before_scrolling_ancestors(cx: &mut TestAppContext) {
        cx.update(crate::theme::init);
        for parent_kind in 0..3 {
            for (tabs, at_end) in [(6, false), (6, true), (1, false)] {
                let scroll_handle = ScrollHandle::new();
                let parent = match parent_kind {
                    0 => WheelParent::Div(ScrollHandle::new()),
                    1 => WheelParent::List(
                        gpui::ListState::new(10, gpui::ListAlignment::Top, px(0.)).measure_all(),
                    ),
                    _ => WheelParent::Scrollable,
                };
                let (_, cx) = cx.add_window_view({
                    let scroll_handle = scroll_handle.clone();
                    let parent = parent.clone();
                    move |_, _| NestedWheelHarness {
                        parent,
                        scroll_handle,
                        tabs,
                    }
                });
                draw(cx);
                draw(cx);
                if let WheelParent::List(state) = &parent {
                    assert!(state.max_offset_for_scrollbar().y > px(0.));
                }
                if at_end {
                    scroll_handle.set_offset(point(-scroll_handle.max_offset().x, px(0.)));
                    draw(cx);
                }
                let before_x = scroll_handle.offset().x;
                let first_before = cx.debug_bounds("wheel-tab-0").unwrap();
                let position = scroll_handle.bounds().center();
                assert_eq!(parent.offset().unwrap_or_default(), (0, px(0.)));
                wheel(
                    cx,
                    position,
                    gpui::ScrollDelta::Lines(point(0., -1.)),
                    gpui::TouchPhase::Moved,
                );
                let first_after = cx.debug_bounds("wheel-tab-0").unwrap();
                if tabs > 1 && !at_end {
                    assert!(scroll_handle.offset().x < before_x);
                    assert!(first_after.left() < first_before.left());
                    assert_eq!(parent.offset().unwrap_or_default(), (0, px(0.)));
                    assert_eq!(first_after.top(), first_before.top());
                } else {
                    assert_eq!(scroll_handle.offset().x, before_x);
                    if let Some(offset) = parent.offset() {
                        assert_ne!(
                            offset,
                            (0, px(0.)),
                            "parent {parent_kind}, tabs {tabs}, at_end {at_end}, before_x {before_x:?}, first_before {first_before:?}, after {first_after:?}"
                        );
                    }
                    assert!(first_after.top() < first_before.top());
                }
            }
        }
    }

    struct WheelLineHeightHarness {
        scroll_handle: ScrollHandle,
        font_size: Pixels,
        line_height: Pixels,
    }

    impl Render for WheelLineHeightHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            // The scroll viewport inherits these values. Tab's own label styling
            // is below that viewport and must not determine its wheel distance.
            div()
                .w(px(160.))
                .h(px(64.))
                .text_size(self.font_size)
                .line_height(self.line_height)
                .child(wheel_tabs(Some(&self.scroll_handle), TabVariant::Tab, 6))
        }
    }

    #[gpui::test]
    fn vertical_mouse_wheel_uses_the_scroll_viewports_inherited_line_height(
        cx: &mut TestAppContext,
    ) {
        cx.update(crate::theme::init);
        for (font_size, line_height) in [(px(12.), px(18.)), (px(24.), px(48.))] {
            let scroll_handle = ScrollHandle::new();
            let (_, cx) = cx.add_window_view({
                let scroll_handle = scroll_handle.clone();
                move |_, _| WheelLineHeightHarness {
                    scroll_handle,
                    font_size,
                    line_height,
                }
            });
            draw(cx);
            draw(cx);
            let first_before = cx.debug_bounds("wheel-tab-0").unwrap();
            assert!(scroll_handle.max_offset().x > line_height);
            assert_eq!(scroll_handle.offset(), point(px(0.), px(0.)));

            // Use actual tab geometry: a wrapping div can have zero auto height
            // while its overflowing children still paint and accept input.
            let position = first_before.center();
            wheel(
                cx,
                position,
                gpui::ScrollDelta::Lines(point(0., -1.)),
                gpui::TouchPhase::Moved,
            );
            assert_eq!(
                scroll_handle.offset(),
                point(-line_height, px(0.)),
                "font {font_size:?}, line height {line_height:?}"
            );
            let first_after = cx.debug_bounds("wheel-tab-0").unwrap();
            assert_eq!(first_after.left() - first_before.left(), -line_height);
            assert_eq!(first_after.top(), first_before.top());

            wheel(
                cx,
                position,
                gpui::ScrollDelta::Lines(point(0., 1.)),
                gpui::TouchPhase::Moved,
            );
            assert_eq!(scroll_handle.offset(), point(px(0.), px(0.)));
            assert_eq!(cx.debug_bounds("wheel-tab-0").unwrap(), first_before);
        }
    }

    struct WheelHitboxHarness {
        scroll_handle: ScrollHandle,
        occluded: bool,
    }

    impl Render for WheelHitboxHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .relative()
                .w(px(240.))
                .h(px(64.))
                .child(
                    wheel_tabs(Some(&self.scroll_handle), TabVariant::Tab, 6)
                        .prefix(
                            div()
                                .w(px(40.))
                                .h(px(32.))
                                .debug_selector(|| "wheel-prefix".into())
                                .child("P"),
                        )
                        .suffix(
                            div()
                                .w(px(40.))
                                .h(px(32.))
                                .debug_selector(|| "wheel-suffix".into())
                                .child("S"),
                        ),
                )
                .when(self.occluded, |this| {
                    this.child(
                        div()
                            .absolute()
                            .inset_0()
                            .occlude()
                            .debug_selector(|| "wheel-occluder".into()),
                    )
                })
        }
    }

    #[gpui::test]
    fn vertical_mouse_wheel_respects_the_viewport_and_occluding_surfaces(cx: &mut TestAppContext) {
        cx.update(crate::theme::init);
        let scroll_handle = ScrollHandle::new();
        let (view, cx) = cx.add_window_view({
            let scroll_handle = scroll_handle.clone();
            move |_, _| WheelHitboxHarness {
                scroll_handle,
                occluded: false,
            }
        });
        draw(cx);
        draw(cx);
        let first_before = cx.debug_bounds("wheel-tab-0").unwrap();
        assert!(scroll_handle.max_offset().x > px(0.));
        assert_eq!(scroll_handle.offset(), point(px(0.), px(0.)));

        for selector in ["wheel-prefix", "wheel-suffix"] {
            let position = cx.debug_bounds(selector).unwrap().center();
            assert!(!scroll_handle.bounds().contains(&position));
            wheel(
                cx,
                position,
                gpui::ScrollDelta::Lines(point(0., -1.)),
                gpui::TouchPhase::Moved,
            );
            assert_eq!(scroll_handle.offset(), point(px(0.), px(0.)));
            assert_eq!(cx.debug_bounds("wheel-tab-0").unwrap(), first_before);
        }

        view.update(cx, |view, cx| {
            view.occluded = true;
            cx.notify();
        });
        draw(cx);
        let position = scroll_handle.bounds().center();
        let occluder = cx.debug_bounds("wheel-occluder").unwrap();
        assert!(occluder.size.width > px(0.) && occluder.size.height > px(0.));
        assert!(occluder.contains(&position));
        wheel(
            cx,
            position,
            gpui::ScrollDelta::Lines(point(0., -1.)),
            gpui::TouchPhase::Moved,
        );
        assert_eq!(scroll_handle.offset(), point(px(0.), px(0.)));
        assert_eq!(cx.debug_bounds("wheel-tab-0").unwrap(), first_before);

        view.update(cx, |view, cx| {
            view.occluded = false;
            cx.notify();
        });
        draw(cx);
        wheel(
            cx,
            position,
            gpui::ScrollDelta::Lines(point(0., -1.)),
            gpui::TouchPhase::Moved,
        );
        assert!(scroll_handle.offset().x < px(0.));
        let first_after = cx.debug_bounds("wheel-tab-0").unwrap();
        assert!(first_after.left() < first_before.left());
        assert_eq!(first_after.top(), first_before.top());
    }

    /// A bar of two underlined tabs, the first selected, in a box `width`
    /// wide, which the view shows once `shown`.
    struct LateBar {
        shown: bool,
        width: Pixels,
    }

    impl Render for LateBar {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            div()
                .w(self.width)
                .overflow_hidden()
                .when(self.shown, |this| {
                    this.child(
                        TabBar::new("late-tabs")
                            .underline()
                            .selected_index(0)
                            .child(Tab::new().label("First"))
                            .child(Tab::new().label("Second")),
                    )
                })
        }
    }

    /// Shows a bar in a window drawn before, as a view shows one once its
    /// data came, and draws the bar's first frame.
    fn show_late_bar(cx: &mut TestAppContext, width: Pixels) -> &mut gpui::VisualTestContext {
        cx.update(crate::theme::init);
        let (view, cx) = cx.add_window_view(move |_, _| LateBar {
            shown: false,
            width,
        });
        draw(cx);
        view.update(cx, |bar, cx| {
            bar.shown = true;
            cx.notify();
        });
        draw(cx);
        cx
    }

    /// The underline indicators the frame drawn last painted.
    fn painted_indicators(cx: &mut gpui::VisualTestContext) -> Vec<Bounds<Pixels>> {
        cx.update(|window, cx| {
            let primary: Background = cx.theme().tokens.primary.into();
            let scale_factor = window.scale_factor();
            window
                .painted_quads()
                .into_iter()
                .filter(|quad| quad.background == primary)
                .map(|quad| quad.bounds.map(|value| px(value.0 / scale_factor)))
                .filter(|bounds| bounds.size.height == px(2.))
                .collect()
        })
    }

    /// The frame after a bar's first, which measured its tabs, draws the
    /// indicator under the selected tab, though nothing the view holding
    /// the bar renders from changed. Then the bar asks for no more frames.
    #[gpui::test]
    fn a_bar_shown_later_draws_its_indicator_on_the_next_frame(cx: &mut TestAppContext) {
        let cx = show_late_bar(cx, px(300.));
        next_frame(cx);
        let indicators = painted_indicators(cx);
        assert_eq!(indicators.len(), 1, "{indicators:?}");
        assert!(indicators[0].size.width > px(0.), "{indicators:?}");
        assert!(indicators[0].right() <= px(150.), "{indicators:?}");
        assert_eq!(cx.update(|window, cx| window.simulate_next_frame(cx)), 0);
    }

    /// A bar squeezed to no width asks for no frames to place its indicator.
    #[gpui::test]
    fn a_bar_with_no_width_asks_for_no_frames(cx: &mut TestAppContext) {
        let cx = show_late_bar(cx, px(0.));
        next_frame(cx);
        assert_eq!(cx.update(|window, cx| window.simulate_next_frame(cx)), 0);
    }
}
