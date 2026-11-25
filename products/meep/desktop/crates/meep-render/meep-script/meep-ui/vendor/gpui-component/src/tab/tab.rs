use std::{rc::Rc, time::Duration};

use crate::animation::{Lerp, ease_in_out_cubic};
use crate::{ActiveTheme, Icon, IconName, Selectable, Sizable, Size, StyledExt, h_flex};
use gpui::prelude::FluentBuilder as _;
use gpui::{
    Animation, AnimationExt as _, AnyElement, App, Background, ClickEvent, Edges, ElementId,
    FillOptions, Hsla, InteractiveElement, IntoElement, ParentElement, PathBuilder, PathStyle,
    Pixels, Point, RenderOnce, SharedString, StatefulInteractiveElement, Styled, Window, canvas,
    div, point, px, relative,
};

/// Room between two [`TabVariant::Folder`] tabs, holding their separator.
pub(super) const FOLDER_TAB_GAP: Pixels = px(4.);

/// Geometry of [`TabVariant::Folder`].
#[derive(Clone, Copy)]
pub(super) struct FolderTabMetrics {
    /// Bar space above the tabs. The content sits this much above the tab's
    /// center so that it centers on the whole bar.
    pub(super) top_padding: Pixels,
    /// Radius of the top corners and of the curves joining the selected tab
    /// to the content below.
    pub(super) radius: Pixels,
    pub(super) padding_x: Pixels,
    pub(super) separator_height: Pixels,
}

impl FolderTabMetrics {
    pub(super) fn new(size: Size, cx: &App) -> Self {
        let (top_padding, padding_x, separator_height, radius) = match size {
            Size::XSmall => (px(2.), px(8.), px(12.), cx.theme().radius),
            Size::Small => (px(4.), px(8.), px(12.), cx.theme().radius),
            Size::Large => (px(8.), px(16.), px(16.), cx.theme().radius_lg),
            _ => (px(4.), px(12.), px(16.), cx.theme().radius_lg),
        };
        Self {
            top_padding,
            // Past a third of the height a curve reaches under its neighbor's
            // hover fill.
            radius: radius.min(TabVariant::Folder.height(size) / 3.),
            padding_x,
            separator_height,
        }
    }
}

/// Tab variants.
#[derive(Debug, Clone, Default, Copy, PartialEq, Eq, Hash)]
pub enum TabVariant {
    #[default]
    Tab,
    Outline,
    Pill,
    Segmented,
    Underline,
    /// Tabs shaped like a folder's index tabs, as in a web browser: the
    /// selected tab rises from the bar with rounded top corners and curves out
    /// into the content below it.
    Folder,
}

impl TabVariant {
    fn height(&self, size: Size) -> Pixels {
        match size {
            Size::XSmall => match self {
                TabVariant::Underline => px(26.),
                _ => px(20.),
            },
            Size::Small => match self {
                TabVariant::Underline => px(30.),
                _ => px(24.),
            },
            Size::Large => match self {
                TabVariant::Underline => px(44.),
                _ => px(36.),
            },
            _ => match self {
                TabVariant::Underline => px(36.),
                _ => px(32.),
            },
        }
    }

    pub(super) fn inner_height(&self, size: Size) -> Pixels {
        match size {
            Size::XSmall => match self {
                TabVariant::Tab | TabVariant::Outline | TabVariant::Pill => px(18.),
                TabVariant::Segmented | TabVariant::Folder => px(16.),
                TabVariant::Underline => px(20.),
            },
            Size::Small => match self {
                TabVariant::Tab | TabVariant::Outline | TabVariant::Pill => px(22.),
                TabVariant::Segmented | TabVariant::Folder => px(18.),
                TabVariant::Underline => px(22.),
            },
            Size::Large => match self {
                TabVariant::Tab | TabVariant::Outline | TabVariant::Pill => px(36.),
                TabVariant::Segmented | TabVariant::Folder => px(28.),
                TabVariant::Underline => px(32.),
            },
            _ => match self {
                TabVariant::Tab => px(30.),
                TabVariant::Outline | TabVariant::Pill => px(26.),
                TabVariant::Segmented | TabVariant::Folder => px(24.),
                TabVariant::Underline => px(26.),
            },
        }
    }

    /// Default px(12) to match a dock tab bar's px_3
    fn inner_paddings(&self, size: Size) -> Edges<Pixels> {
        let mut padding_x = match size {
            Size::XSmall => px(8.),
            Size::Small => px(10.),
            Size::Large => px(16.),
            _ => px(12.),
        };

        // A folder tab pads its content itself, see `FolderTabMetrics`.
        if matches!(self, TabVariant::Underline | TabVariant::Folder) {
            padding_x = px(0.);
        }

        Edges {
            left: padding_x,
            right: padding_x,
            ..Default::default()
        }
    }

    fn inner_margins(&self, size: Size) -> Edges<Pixels> {
        match size {
            Size::XSmall => match self {
                TabVariant::Underline => Edges {
                    top: px(1.),
                    bottom: px(2.),
                    ..Default::default()
                },
                _ => Edges::all(px(0.)),
            },
            Size::Small => match self {
                TabVariant::Underline => Edges {
                    top: px(2.),
                    bottom: px(3.),
                    ..Default::default()
                },
                _ => Edges::all(px(0.)),
            },
            Size::Large => match self {
                TabVariant::Underline => Edges {
                    top: px(5.),
                    bottom: px(6.),
                    ..Default::default()
                },
                _ => Edges::all(px(0.)),
            },
            _ => match self {
                TabVariant::Underline => Edges {
                    top: px(3.),
                    bottom: px(4.),
                    ..Default::default()
                },
                _ => Edges::all(px(0.)),
            },
        }
    }

    fn normal(&self, cx: &App) -> TabStyle {
        match self {
            TabVariant::Tab => TabStyle {
                fg: cx.theme().tab_foreground,
                bg: cx.theme().transparent.into(),
                borders: Edges {
                    left: px(1.),
                    right: px(1.),
                    ..Default::default()
                },
                border_color: cx.theme().transparent,
                ..Default::default()
            },
            TabVariant::Outline => TabStyle {
                fg: cx.theme().tab_foreground,
                bg: cx.theme().transparent.into(),
                borders: Edges::all(px(1.)),
                border_color: cx.theme().border,
                ..Default::default()
            },
            TabVariant::Pill => TabStyle {
                fg: cx.theme().foreground,
                bg: cx.theme().transparent.into(),
                ..Default::default()
            },
            TabVariant::Segmented => TabStyle {
                fg: cx.theme().tab_foreground,
                bg: cx.theme().transparent.into(),
                ..Default::default()
            },
            TabVariant::Underline => TabStyle {
                fg: cx.theme().tab_foreground,
                bg: cx.theme().transparent.into(),
                inner_bg: cx.theme().transparent.into(),
                borders: Edges {
                    bottom: px(2.),
                    ..Default::default()
                },
                border_color: cx.theme().transparent,
                ..Default::default()
            },
            TabVariant::Folder => TabStyle {
                fg: cx.theme().tab_foreground,
                bg: cx.theme().transparent.into(),
                ..Default::default()
            },
        }
    }

    fn hovered(&self, selected: bool, cx: &App) -> TabStyle {
        match self {
            TabVariant::Tab => TabStyle {
                fg: cx.theme().tab_active_foreground,
                bg: cx.theme().transparent.into(),
                borders: Edges {
                    left: px(1.),
                    right: px(1.),
                    ..Default::default()
                },
                border_color: cx.theme().transparent,
                ..Default::default()
            },
            TabVariant::Outline => TabStyle {
                fg: cx.theme().secondary_foreground,
                bg: cx.theme().tokens.secondary_hover.into(),
                borders: Edges::all(px(1.)),
                border_color: cx.theme().border,
                ..Default::default()
            },
            TabVariant::Pill => TabStyle {
                fg: cx.theme().secondary_foreground,
                bg: cx.theme().tokens.secondary.into(),
                ..Default::default()
            },
            TabVariant::Segmented => TabStyle {
                fg: cx.theme().tab_active_foreground,
                bg: cx.theme().transparent.into(),
                inner_bg: if selected {
                    cx.theme().tokens.background.into()
                } else {
                    cx.theme().transparent.into()
                },
                ..Default::default()
            },
            TabVariant::Underline => TabStyle {
                fg: cx.theme().tab_active_foreground,
                bg: cx.theme().transparent.into(),
                inner_bg: cx.theme().transparent.into(),
                borders: Edges {
                    bottom: px(2.),
                    ..Default::default()
                },
                border_color: cx.theme().transparent,
                ..Default::default()
            },
            // The hover fill is an inset rounded layer, see `Tab::render`.
            TabVariant::Folder => TabStyle {
                fg: cx.theme().tab_active_foreground,
                bg: cx.theme().transparent.into(),
                ..Default::default()
            },
        }
    }

    fn selected(&self, cx: &App) -> TabStyle {
        match self {
            TabVariant::Tab => TabStyle {
                fg: cx.theme().tab_active_foreground,
                bg: cx.theme().tokens.tab_active.into(),
                borders: Edges {
                    left: px(1.),
                    right: px(1.),
                    ..Default::default()
                },
                border_color: cx.theme().border,
                ..Default::default()
            },
            TabVariant::Outline => TabStyle {
                fg: cx.theme().primary,
                bg: cx.theme().transparent.into(),
                borders: Edges::all(px(1.)),
                border_color: cx.theme().primary,
                ..Default::default()
            },
            TabVariant::Pill => TabStyle {
                fg: cx.theme().primary_foreground,
                bg: cx.theme().tokens.primary.into(),
                ..Default::default()
            },
            TabVariant::Segmented => TabStyle {
                fg: cx.theme().tab_active_foreground,
                bg: cx.theme().transparent.into(),
                inner_bg: cx.theme().tokens.background.into(),
                shadow: true,
                ..Default::default()
            },
            TabVariant::Underline => TabStyle {
                fg: cx.theme().tab_active_foreground,
                bg: cx.theme().transparent.into(),
                borders: Edges {
                    bottom: px(2.),
                    ..Default::default()
                },
                border_color: cx.theme().primary,
                ..Default::default()
            },
            // The shape is painted by `folder_tab_shape`.
            TabVariant::Folder => TabStyle {
                fg: cx.theme().tab_active_foreground,
                bg: cx.theme().transparent.into(),
                ..Default::default()
            },
        }
    }

    fn disabled(&self, selected: bool, cx: &App) -> TabStyle {
        match self {
            TabVariant::Tab => TabStyle {
                fg: cx.theme().muted_foreground,
                bg: cx.theme().transparent.into(),
                border_color: if selected {
                    cx.theme().border
                } else {
                    cx.theme().transparent
                },
                borders: Edges {
                    left: px(1.),
                    right: px(1.),
                    ..Default::default()
                },
                ..Default::default()
            },
            TabVariant::Outline => TabStyle {
                fg: cx.theme().muted_foreground,
                bg: cx.theme().transparent.into(),
                borders: Edges::all(px(1.)),
                border_color: if selected {
                    cx.theme().primary
                } else {
                    cx.theme().border
                },
                ..Default::default()
            },
            TabVariant::Pill => TabStyle {
                fg: if selected {
                    cx.theme().primary_foreground.opacity(0.5)
                } else {
                    cx.theme().muted_foreground
                },
                bg: if selected {
                    cx.theme().primary.opacity(0.5).into()
                } else {
                    cx.theme().transparent.into()
                },
                ..Default::default()
            },
            TabVariant::Segmented => TabStyle {
                fg: cx.theme().muted_foreground,
                bg: cx.theme().tokens.tab_bar.into(),
                inner_bg: if selected {
                    cx.theme().tokens.background.into()
                } else {
                    cx.theme().transparent.into()
                },
                ..Default::default()
            },
            TabVariant::Underline => TabStyle {
                fg: cx.theme().muted_foreground,
                bg: cx.theme().transparent.into(),
                border_color: if selected {
                    cx.theme().border
                } else {
                    cx.theme().transparent
                },
                borders: Edges {
                    bottom: px(2.),
                    ..Default::default()
                },
                ..Default::default()
            },
            TabVariant::Folder => TabStyle {
                fg: cx.theme().muted_foreground,
                bg: cx.theme().transparent.into(),
                ..Default::default()
            },
        }
    }

    pub(super) fn tab_bar_radius(&self, size: Size, cx: &App) -> Pixels {
        if *self != TabVariant::Segmented {
            return px(0.);
        }

        match size {
            Size::XSmall | Size::Small => cx.theme().radius,
            Size::Large => cx.theme().radius_lg,
            _ => cx.theme().radius_lg,
        }
    }

    fn radius(&self, size: Size, cx: &App) -> Pixels {
        match self {
            TabVariant::Outline | TabVariant::Pill => cx.theme().radius_full(),
            TabVariant::Segmented => match size {
                Size::XSmall | Size::Small => cx.theme().radius,
                Size::Large => cx.theme().radius_lg,
                _ => cx.theme().radius_lg,
            },
            _ => px(0.),
        }
    }

    pub(super) fn inner_radius(&self, size: Size, cx: &App) -> Pixels {
        match self {
            // The inset the active pill sits at, taken off the bar's own radius
            // so the two curves stay concentric. Floored at zero: a square bar
            // has nothing to inset from.
            TabVariant::Segmented => match size {
                Size::Large => (self.tab_bar_radius(size, cx) - px(3.)).max(px(0.)),
                _ => (self.tab_bar_radius(size, cx) - px(2.)).max(px(0.)),
            },
            _ => px(0.),
        }
    }

    /// How far a tab's painting reaches past its bounds on either side.
    pub(super) fn overhang(&self, size: Size, cx: &App) -> Pixels {
        match self {
            TabVariant::Folder => FolderTabMetrics::new(size, cx).radius,
            _ => px(0.),
        }
    }
}

/// The selected [`TabVariant::Folder`] tab: rounded on top and curving out at
/// the bottom into the content below, traced after Chrome's tab path.
fn folder_tab_shape(metrics: FolderTabMetrics, bg: Background) -> impl IntoElement {
    let curve = metrics.radius;
    canvas(
        |_, _, _| {},
        move |bounds, _, window, _| {
            let (top, bottom) = (bounds.top(), bounds.bottom());
            let (left, right) = (bounds.left(), bounds.right());
            let (tab_left, tab_right) = (left + curve, right - curve);
            // Like Chrome, keep at least a third of the top flat on narrow tabs.
            let radius = ((bounds.size.width - curve * 2.) / 3.).clamp(px(0.), curve);

            let mut path =
                PathBuilder::fill().with_style(PathStyle::Fill(FillOptions::tolerance(0.02)));
            path.move_to(point(left, bottom));
            quarter_circle_to(
                &mut path,
                point(left, bottom),
                point(tab_left, bottom),
                point(tab_left, bottom - curve),
            );
            path.line_to(point(tab_left, top + radius));
            quarter_circle_to(
                &mut path,
                point(tab_left, top + radius),
                point(tab_left, top),
                point(tab_left + radius, top),
            );
            path.line_to(point(tab_right - radius, top));
            quarter_circle_to(
                &mut path,
                point(tab_right - radius, top),
                point(tab_right, top),
                point(tab_right, top + radius),
            );
            path.line_to(point(tab_right, bottom - curve));
            quarter_circle_to(
                &mut path,
                point(tab_right, bottom - curve),
                point(tab_right, bottom),
                point(right, bottom),
            );
            path.close();
            if let Ok(path) = path.build() {
                window.paint_path(path, bg);
            }
        },
    )
    .absolute()
    .top_0()
    .bottom_0()
    .left(-curve)
    .right(-curve)
}

/// Adds a quarter circle from `from` to `to`, whose tangents meet at `corner`.
fn quarter_circle_to(
    path: &mut PathBuilder,
    from: Point<Pixels>,
    corner: Point<Pixels>,
    to: Point<Pixels>,
) {
    // Control point distance that makes a cubic Bézier a quarter circle.
    const K: f32 = 0.552_284_8;
    path.cubic_bezier_to(to, from + (corner - from) * K, to + (corner - to) * K);
}

#[allow(dead_code)]
struct TabStyle {
    borders: Edges<Pixels>,
    border_color: Hsla,
    bg: Background,
    fg: Hsla,
    shadow: bool,
    inner_bg: Background,
}

impl Default for TabStyle {
    fn default() -> Self {
        TabStyle {
            borders: Edges::all(px(0.)),
            border_color: gpui::transparent_white(),
            bg: gpui::transparent_white().into(),
            fg: gpui::transparent_white(),
            shadow: false,
            inner_bg: gpui::transparent_white().into(),
        }
    }
}

/// A Tab element for the [`super::TabBar`].
#[derive(IntoElement)]
pub struct Tab {
    ix: usize,
    base: gpui_base::Tab,
    pub(super) label: Option<SharedString>,
    aria_label: Option<SharedString>,
    pub(super) icon: Option<Icon>,
    prefix: Option<AnyElement>,
    pub(super) tab_bar_prefix: Option<bool>,
    suffix: Option<AnyElement>,
    children: Vec<AnyElement>,
    variant: TabVariant,
    size: Size,
    pub(super) disabled: bool,
    pub(super) selected: bool,
    pub(super) indicator_active: bool,
    pub(super) indicator_ready: bool,
    /// Animation epoch of the [`super::TabBar`] indicator; increments on every
    /// tab switch. Used to key the selected tab's text color fade so it
    /// restarts in sync with the indicator slide.
    pub(super) indicator_epoch: u64,
    /// Whether a [`TabVariant::Folder`] tab draws the divider after it.
    pub(super) separator: bool,
    /// Whether the [`super::TabBar`] reports the pointer over this tab. Kept
    /// there rather than in a hover group, which would replace the caller's.
    pub(super) hovered: bool,
    pub(super) max_width: Option<Pixels>,
    pub(super) on_click: Option<Rc<dyn Fn(&ClickEvent, &mut Window, &mut App) + 'static>>,
}

impl From<&'static str> for Tab {
    fn from(label: &'static str) -> Self {
        Self::new().label(label)
    }
}

impl From<String> for Tab {
    fn from(label: String) -> Self {
        Self::new().label(label)
    }
}

impl From<SharedString> for Tab {
    fn from(label: SharedString) -> Self {
        Self::new().label(label)
    }
}

impl From<Icon> for Tab {
    fn from(icon: Icon) -> Self {
        Self::default().icon(icon)
    }
}

impl From<IconName> for Tab {
    fn from(icon_name: IconName) -> Self {
        Self::default().icon(Icon::new(icon_name))
    }
}

impl Default for Tab {
    fn default() -> Self {
        Self {
            ix: 0,
            base: gpui_base::Tab::new(0usize),
            label: None,
            aria_label: None,
            icon: None,
            tab_bar_prefix: None,
            children: Vec::new(),
            disabled: false,
            selected: false,
            indicator_active: false,
            indicator_ready: true,
            indicator_epoch: 0,
            separator: false,
            hovered: false,
            prefix: None,
            suffix: None,
            variant: TabVariant::default(),
            size: Size::default(),
            max_width: None,
            on_click: None,
        }
    }
}

impl Tab {
    /// Create a new tab with a label.
    pub fn new() -> Self {
        Self::default()
    }

    /// Set label for the tab.
    pub fn label(mut self, label: impl Into<SharedString>) -> Self {
        self.label = Some(label.into());
        self
    }

    /// Set the accessible label for the tab.
    pub fn aria_label(mut self, label: impl Into<SharedString>) -> Self {
        self.aria_label = Some(label.into());
        self
    }

    fn a11y_label(&self) -> Option<SharedString> {
        self.aria_label.clone().or_else(|| self.label.clone())
    }

    /// Set icon for the tab.
    pub fn icon(mut self, icon: impl Into<Icon>) -> Self {
        self.icon = Some(icon.into());
        self
    }

    /// Set Tab Variant.
    pub fn with_variant(mut self, variant: TabVariant) -> Self {
        self.variant = variant;
        self
    }

    /// Use Pill variant.
    pub fn pill(mut self) -> Self {
        self.variant = TabVariant::Pill;
        self
    }

    /// Use outline variant.
    pub fn outline(mut self) -> Self {
        self.variant = TabVariant::Outline;
        self
    }

    /// Use Segmented variant.
    pub fn segmented(mut self) -> Self {
        self.variant = TabVariant::Segmented;
        self
    }

    /// Use Underline variant.
    pub fn underline(mut self) -> Self {
        self.variant = TabVariant::Underline;
        self
    }

    /// Use Folder variant.
    pub fn folder(mut self) -> Self {
        self.variant = TabVariant::Folder;
        self
    }

    /// Set the left side of the tab
    pub fn prefix(mut self, prefix: impl IntoElement) -> Self {
        self.prefix = Some(prefix.into_any_element());
        self
    }

    /// Set the right side of the tab
    pub fn suffix(mut self, suffix: impl IntoElement) -> Self {
        self.suffix = Some(suffix.into_any_element());
        self
    }

    /// Set disabled state to the tab, default false.
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Set the click handler for the tab.
    pub fn on_click(
        mut self,
        on_click: impl Fn(&ClickEvent, &mut Window, &mut App) + 'static,
    ) -> Self {
        self.on_click = Some(Rc::new(on_click));
        self
    }

    /// Set index to the tab.
    pub(crate) fn ix(mut self, ix: usize) -> Self {
        self.ix = ix;
        self.base = self.base.id(ix);
        self
    }

    /// Set if the tab bar has a prefix.
    pub(crate) fn tab_bar_prefix(mut self, tab_bar_prefix: bool) -> Self {
        self.tab_bar_prefix = Some(tab_bar_prefix);
        self
    }

    /// Set the maximum width of the tab, see [`super::TabBar::max_width`].
    pub(super) fn max_width(mut self, max_width: Option<Pixels>) -> Self {
        self.max_width = max_width;
        self
    }
}

impl ParentElement for Tab {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Selectable for Tab {
    fn selected(mut self, selected: bool) -> Self {
        self.selected = selected;
        self
    }

    fn is_selected(&self) -> bool {
        self.selected
    }
}

impl InteractiveElement for Tab {
    fn interactivity(&mut self) -> &mut gpui::Interactivity {
        self.base.interactivity()
    }
}

impl StatefulInteractiveElement for Tab {}

impl Styled for Tab {
    fn style(&mut self) -> &mut gpui::StyleRefinement {
        self.base.style()
    }
}

impl Sizable for Tab {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl RenderOnce for Tab {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let mut normal_style = self.variant.normal(cx);
        let mut selected_style = self.variant.selected(cx);
        let mut disabled_style = self.variant.disabled(self.selected, cx);
        let mut hover_style = self.variant.hovered(self.selected, cx);
        if self.disabled {
            hover_style = self.variant.disabled(self.selected, cx);
        }
        let tab_bar_prefix = self.tab_bar_prefix.unwrap_or_default();
        if !tab_bar_prefix {
            if self.ix == 0 && self.variant == TabVariant::Tab {
                normal_style.borders.left = px(0.);
                selected_style.borders.left = px(0.);
                disabled_style.borders.left = px(0.);
                hover_style.borders.left = px(0.);
            }
        }
        let tab_style = if self.disabled {
            &disabled_style
        } else if self.selected {
            &selected_style
        } else {
            &normal_style
        };
        let radius = self.variant.radius(self.size, cx);
        let inner_radius = self.variant.inner_radius(self.size, cx);
        let inner_paddings = self.variant.inner_paddings(self.size);
        let inner_margins = self.variant.inner_margins(self.size);
        let inner_height = self.variant.inner_height(self.size);
        let height = self.variant.height(self.size);
        let aria_label = self.a11y_label();
        let folder = self.variant == TabVariant::Folder;
        let metrics = FolderTabMetrics::new(self.size, cx);
        let has_prefix = self.prefix.is_some();

        let segmented_indicator_active =
            self.variant == TabVariant::Segmented && self.indicator_active;
        let has_inline_inner_bg =
            self.selected && segmented_indicator_active && !self.indicator_ready;
        let inline_inner_bg = tab_style.inner_bg;
        let (inner_bg, hover_inner_bg) = if segmented_indicator_active && self.indicator_ready {
            (cx.theme().transparent.into(), cx.theme().transparent.into())
        } else if has_inline_inner_bg {
            (inline_inner_bg, inline_inner_bg)
        } else {
            (tab_style.inner_bg, hover_style.inner_bg)
        };
        let inner_shadow = tab_style.shadow && !segmented_indicator_active;

        // When a sliding indicator is active and ready, it alone represents the
        // selected state. Suppress the selected tab's own active background/border
        // so the two don't overlap during the switch animation (Segmented already
        // does this for its `inner_bg` above). Skip disabled tabs so a
        // disabled-selected tab keeps its dimmed styling instead of the
        // full-strength indicator color.
        let suppress_active_visual =
            self.selected && !self.disabled && self.indicator_active && self.indicator_ready;
        // Pill paints its active state via the outer `bg`.
        let selected_outer_bg = if suppress_active_visual && self.variant == TabVariant::Pill {
            cx.theme().transparent.into()
        } else {
            selected_style.bg
        };
        // Underline paints its active state via the bottom `border_color`.
        let selected_outer_border_color =
            if suppress_active_visual && self.variant == TabVariant::Underline {
                cx.theme().transparent
            } else {
                selected_style.border_color
            };

        // For Pill, the newly selected tab's text color (`primary_foreground`)
        // would otherwise snap to white instantly while the indicator is still
        // sliding into place. Fade it from the normal color in sync with the
        // indicator slide (keyed on the indicator epoch so it restarts on each
        // switch). `epoch == 0` is the initial layout (no slide), so we skip it.
        let animate_fg = self.selected
            && !self.disabled
            && self.variant == TabVariant::Pill
            && self.indicator_active
            && self.indicator_ready
            && self.indicator_epoch > 0;
        let fg_from = self.variant.normal(cx).fg;
        let fg_to = tab_style.fg;
        // Icon-only tabs are fixed-size and exempt from `max_width`.
        let max_width = self.max_width.filter(|_| self.icon.is_none());

        let inner_content = h_flex()
            .flex_1()
            .h(inner_height)
            .line_height(relative(1.25))
            .whitespace_nowrap()
            .items_center()
            .justify_center()
            .overflow_hidden()
            .margins(inner_margins)
            // Normally the label decides the tab width, so it never shrinks. With
            // `max_width` it is the one part that gives way.
            .map(|this| match max_width {
                Some(_) => this.flex_auto(),
                None => this.flex_shrink_0(),
            })
            .map(|this| match self.icon {
                Some(icon) => this
                    .w(inner_height * 1.25)
                    .child(icon.map(|this| match self.size {
                        Size::XSmall => this.size_2p5(),
                        Size::Small => this.size_3p5(),
                        Size::Large => this.size_4(),
                        _ => this.size_4(),
                    })),
                None => this
                    .paddings(inner_paddings)
                    .map(|this| match (self.label, max_width) {
                        // Text always takes its natural width, so it needs a box
                        // that is allowed to shrink to ellipsize inside of.
                        (Some(label), Some(_)) => this.child(
                            div()
                                .min_w_0()
                                .whitespace_nowrap()
                                .text_ellipsis()
                                .child(label),
                        ),
                        (Some(label), None) => this.child(label),
                        (None, _) => this,
                    })
                    .children(self.children)
                    // With the prefix's gap, 8px between icon and title, as in a Button.
                    .when(folder && has_prefix, |this| this.pl(px(4.))),
            })
            .bg(inner_bg)
            .rounded(inner_radius)
            .when(inner_shadow, |this| this.shadow_xs())
            .hover(|this| this.bg(hover_inner_bg).rounded(inner_radius));

        let inner_element = if animate_fg {
            inner_content
                .with_animation(
                    ElementId::NamedInteger("tab-fg".into(), self.indicator_epoch),
                    Animation::new(Duration::from_millis(200)).with_easing(ease_in_out_cubic),
                    move |this, delta| this.text_color(Lerp::lerp(&fg_from, &fg_to, delta)),
                )
                .into_any_element()
        } else {
            inner_content.into_any_element()
        };

        self.base
            .id(self.ix)
            .selected(self.selected)
            .disabled(self.disabled)
            .when_some(aria_label, |this, label| this.accessibility_label(label))
            .styles(|styles| {
                styles
                    .selected(|style| {
                        style
                            .text_color(selected_style.fg)
                            .bg(selected_outer_bg)
                            .border_l(selected_style.borders.left)
                            .border_r(selected_style.borders.right)
                            .border_t(selected_style.borders.top)
                            .border_b(selected_style.borders.bottom)
                            .border_color(selected_outer_border_color)
                    })
                    .disabled(|style| {
                        style
                            .text_color(disabled_style.fg)
                            .bg(disabled_style.bg)
                            .border_l(disabled_style.borders.left)
                            .border_r(disabled_style.borders.right)
                            .border_t(disabled_style.borders.top)
                            .border_b(disabled_style.borders.bottom)
                            .border_color(disabled_style.border_color)
                    })
            })
            .relative()
            .flex()
            // Wrapping would move the overflow onto a clipped second line instead
            // of letting the label shrink, so a capped tab lays out on one line.
            .map(|this| match max_width {
                Some(max_width) => this.flex_nowrap().max_w(max_width),
                None => this.flex_wrap(),
            })
            .gap_1()
            .items_center()
            .flex_shrink_0()
            .h(height)
            // A folder tab's curves reach past its bounds.
            .when(!folder, |this| this.overflow_hidden())
            .map(|this| match self.size {
                Size::XSmall => this.text_xs(),
                Size::Large => this.text_base(),
                _ => this.text_sm(),
            })
            .rounded(radius)
            .when(folder, |this| {
                this.px(metrics.padding_x).pb(metrics.top_padding)
            })
            .when(!self.selected && !self.disabled, |this| {
                this.text_color(normal_style.fg)
                    .bg(normal_style.bg)
                    .border_l(normal_style.borders.left)
                    .border_r(normal_style.borders.right)
                    .border_t(normal_style.borders.top)
                    .border_b(normal_style.borders.bottom)
                    .border_color(normal_style.border_color)
            })
            .hover(|this| {
                // Always register the hover style: GPUI only refreshes the cached
                // hover state while one is present. If the selected tab skipped it,
                // the stale state would keep hover colors after unselecting.
                if self.selected || self.disabled {
                    return this;
                }
                this.text_color(hover_style.fg)
                    .bg(hover_style.bg)
                    .border_l(hover_style.borders.left)
                    .border_r(hover_style.borders.right)
                    .border_t(hover_style.borders.top)
                    .border_b(hover_style.borders.bottom)
                    .border_color(hover_style.border_color)
                    .rounded(radius)
            })
            .when(folder && self.selected, |this| {
                this.child(folder_tab_shape(
                    metrics,
                    cx.theme().tokens.tab_active.into(),
                ))
            })
            .when(
                folder && self.hovered && !self.selected && !self.disabled,
                |this| {
                    this.child(
                        div()
                            .absolute()
                            .top_0()
                            .left_0()
                            .right_0()
                            .bottom(metrics.top_padding)
                            .rounded(metrics.radius)
                            .bg(cx.theme().tokens.secondary),
                    )
                },
            )
            // In the gap after the tab, on a whole pixel, level with the content.
            .when(folder && self.separator, |this| {
                this.child(
                    div()
                        .absolute()
                        .right(-(FOLDER_TAB_GAP / 2.))
                        .top((height - metrics.top_padding - metrics.separator_height) / 2.)
                        .w(px(1.))
                        .h(metrics.separator_height)
                        .bg(cx.theme().border),
                )
            })
            .when(has_inline_inner_bg, |this| {
                this.child(
                    div()
                        .absolute()
                        .left_0()
                        .right_0()
                        .top_0()
                        .bottom_0()
                        .flex()
                        .items_center()
                        .child(
                            div()
                                .w_full()
                                .h(inner_height)
                                .bg(inline_inner_bg)
                                .rounded(inner_radius)
                                .when(tab_style.shadow, |this| this.shadow_sm()),
                        ),
                )
            })
            // Under `max_width` the label is the only part that gives way, so
            // hold the prefix and suffix (e.g. a close button) at their full size.
            .when_some(self.prefix, |this, prefix| {
                this.child(
                    div()
                        .when_some(max_width, |this, _| this.flex_shrink_0())
                        .child(prefix),
                )
            })
            .child(inner_element)
            .when_some(self.suffix, |this, suffix| {
                this.child(
                    div()
                        .when_some(max_width, |this, _| this.flex_shrink_0())
                        .child(suffix),
                )
            })
            .when_some(self.on_click.clone(), |this, on_click| {
                this.on_click(move |event, window, cx| on_click(event, window, cx))
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tab::TabBar;
    use gpui::{Context, Render, TestAppContext, VisualTestContext};

    const VARIANTS: [TabVariant; 6] = [
        TabVariant::Tab,
        TabVariant::Outline,
        TabVariant::Pill,
        TabVariant::Segmented,
        TabVariant::Underline,
        TabVariant::Folder,
    ];

    const LONG_LABEL: &str = "Account Settings & Preferences";

    /// One [`TabBar`], optionally capped, holding the tab `build` returns.
    struct TabBarTest {
        variant: TabVariant,
        max_width: Option<Pixels>,
        build: fn(Tab) -> Tab,
    }

    impl Render for TabBarTest {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            TabBar::new("tabs")
                .with_variant(self.variant)
                .selected_index(0)
                .when_some(self.max_width, |this, width| this.max_width(width))
                .child((self.build)(
                    Tab::new().debug_selector(|| "tab".to_string()),
                ))
        }
    }

    fn show(
        cx: &mut TestAppContext,
        variant: TabVariant,
        max_width: Option<Pixels>,
        build: fn(Tab) -> Tab,
    ) -> &mut VisualTestContext {
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| TabBarTest {
            variant,
            max_width,
            build,
        });
        cx.run_until_parked();
        cx
    }

    /// Outer width of a labelled tab in every variant, capped or not.
    fn variant_widths(
        cx: &mut TestAppContext,
        build: fn(Tab) -> Tab,
        max_width: Option<Pixels>,
    ) -> Vec<Pixels> {
        VARIANTS
            .into_iter()
            .map(|variant| {
                show(cx, variant, max_width, build)
                    .debug_bounds("tab")
                    .expect("tab not rendered")
                    .size
                    .width
            })
            .collect()
    }

    #[gpui::test]
    fn a11y_label_defaults_to_visible_label(_cx: &mut TestAppContext) {
        let tab = Tab::new().label("Account");

        assert_eq!(tab.a11y_label(), Some("Account".into()));
    }

    #[gpui::test]
    fn explicit_a11y_label_overrides_visible_label(_cx: &mut TestAppContext) {
        let tab = Tab::new().label("Acct").aria_label("Account settings");

        assert_eq!(tab.a11y_label(), Some("Account settings".into()));
    }

    #[gpui::test]
    fn max_width_leaves_short_tabs_untouched(cx: &mut TestAppContext) {
        // The box the cap wraps the label in must not report a different
        // intrinsic width than the bare label it replaces.
        let build: fn(Tab) -> Tab = |tab| tab.label("Go");

        let uncapped = variant_widths(cx, build, None);
        let capped = variant_widths(cx, build, Some(px(200.)));

        assert_eq!(uncapped, capped, "a tab under the cap must not be resized");
    }

    #[gpui::test]
    fn max_width_caps_long_tabs(cx: &mut TestAppContext) {
        let build: fn(Tab) -> Tab = |tab| tab.label(LONG_LABEL);

        let uncapped = variant_widths(cx, build, None);
        let capped = variant_widths(cx, build, Some(px(120.)));

        for (variant, (uncapped, capped)) in
            VARIANTS.into_iter().zip(uncapped.into_iter().zip(capped))
        {
            assert!(
                uncapped > px(120.),
                "{variant:?} is not long enough to exercise the cap ({uncapped:?})"
            );
            assert!(
                capped <= px(120.),
                "{variant:?} width {capped:?} exceeds max_width"
            );
        }
    }

    #[gpui::test]
    fn max_width_keeps_prefix_and_suffix_intact(cx: &mut TestAppContext) {
        let cx = show(cx, TabVariant::Segmented, Some(px(140.)), |tab| {
            tab.prefix(Icon::new(IconName::BookOpen))
                .label(LONG_LABEL)
                .suffix(div().size(px(16.)).debug_selector(|| "suffix".to_string()))
        });

        let tab = cx.debug_bounds("tab").expect("tab not rendered");
        let suffix = cx.debug_bounds("suffix").expect("suffix not rendered");

        assert!(tab.size.width <= px(140.));
        assert_eq!(
            suffix.size.width,
            px(16.),
            "the label should absorb the truncation, not the suffix"
        );
        assert!(
            suffix.right() <= tab.right(),
            "suffix must stay within the tab"
        );
        // A wrapping tab pushes the suffix onto a second line, which the fixed
        // tab height then clips: it keeps its size and stays inside the tab,
        // but lands back at the left edge instead of after the label.
        assert!(
            suffix.left() > tab.center().x,
            "suffix must follow the label, not wrap below it"
        );
    }

    /// Icon-only tabs are sized to a square by construction, so the cap has to
    /// leave them alone however narrow it is.
    #[gpui::test]
    fn max_width_exempts_icon_only_tabs(cx: &mut TestAppContext) {
        let build: fn(Tab) -> Tab = |tab| tab.icon(Icon::new(IconName::BookOpen));
        let width = |cx: &mut TestAppContext, max_width| {
            show(cx, TabVariant::Tab, max_width, build)
                .debug_bounds("tab")
                .expect("tab not rendered")
                .size
                .width
        };

        let uncapped = width(cx, None);
        assert!(
            uncapped > px(16.),
            "the cap has to be narrower than the icon tab to be meaningful"
        );
        assert_eq!(
            width(cx, Some(px(16.))),
            uncapped,
            "an icon-only tab must ignore max_width"
        );
    }
}
