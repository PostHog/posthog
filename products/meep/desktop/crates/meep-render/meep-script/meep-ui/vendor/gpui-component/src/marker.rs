use crate::{
    ActiveTheme as _, RoleOverride, Sizable as _, StyledExt as _, h_flex,
    shimmer::{ShimmerStyle, ShimmerText},
    spinner::Spinner,
};
use gpui::{
    AnimationExt as _, AnyElement, App, ElementId, InteractiveElement as _, IntoElement,
    ParentElement, RenderOnce, SharedString, StatefulInteractiveElement as _, StyleRefinement,
    Styled, StyledText, Window, div, prelude::FluentBuilder as _, px, relative, rems,
};

/// The visual treatment used by a [`Marker`].
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum MarkerVariant {
    /// An inline marker with no additional divider.
    #[default]
    Plain,
    /// A centered marker with semantic divider lines on both sides.
    Separator,
    /// A marker with a semantic bottom border.
    Border,
}

/// The visual treatment used while a [`Marker`] is loading.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum MarkerLoadingStyle {
    /// Show a compact rotating spinner beside the marker content.
    #[default]
    Spinner,
    /// Sweep a highlight across marker content without adding an icon.
    Shimmer,
}

/// Horizontal placement of a [`Marker`]'s children inside its full-width row.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MarkerAlignment {
    /// Keep the children at the leading edge.
    Start,
    /// Center the children, like a system notice in a transcript.
    Center,
    /// Keep the children at the trailing edge.
    End,
}

enum MarkerChild {
    Icon(MarkerIcon),
    Content(MarkerContent),
    Element(AnyElement),
}

/// A compact, composable row for conversation status and system markers.
///
/// `Marker` intentionally accepts arbitrary children. An icon, text, spinner,
/// or action can be composed directly without introducing fixed icon and
/// content slots. Use [`Styled`] methods on the marker to refine its layout or
/// typography for an application-specific use. Loading effects only affect
/// configured content slots, so icons and separators retain their appearance.
#[derive(IntoElement)]
pub struct Marker {
    id: Option<ElementId>,
    style: StyleRefinement,
    separator_style: StyleRefinement,
    variant: MarkerVariant,
    alignment: Option<MarkerAlignment>,
    loading: bool,
    loading_style: MarkerLoadingStyle,
    shimmer_style: ShimmerStyle,
    role: RoleOverride,
    children: Vec<MarkerChild>,
}

impl Marker {
    /// Create a plain marker.
    pub fn new() -> Self {
        Self {
            id: None,
            style: StyleRefinement::default(),
            separator_style: StyleRefinement::default(),
            variant: MarkerVariant::default(),
            alignment: None,
            loading: false,
            loading_style: MarkerLoadingStyle::default(),
            shimmer_style: ShimmerStyle::default(),
            role: RoleOverride::default(),
            children: Vec::new(),
        }
    }

    /// Set a stable identity so the marker can appear in the accessibility tree.
    pub fn id(mut self, id: impl Into<ElementId>) -> Self {
        self.id = Some(id.into());
        self
    }

    /// Set the accessibility role announced for this marker.
    ///
    /// A marker is presentational by default. Set [`gpui::Role::Status`] on a
    /// row that reports streaming or loading progress so assistive technology
    /// announces its updates. Accessibility nodes need a stable identity, so
    /// the role takes effect only together with [`Self::id`].
    pub fn role(mut self, role: impl Into<RoleOverride>) -> Self {
        self.role = role.into();
        self
    }

    /// Set the visual treatment of the marker.
    pub fn with_variant(mut self, variant: MarkerVariant) -> Self {
        self.variant = variant;
        self
    }

    /// Set where the row places its children.
    ///
    /// Unset, a [`MarkerVariant::Separator`] centers its label between the two
    /// lines and every other variant starts at the leading edge. An explicit
    /// alignment applies to any variant and also aligns wrapped text lines. A
    /// separator keeps only the line on the far side of its label, so `Start`
    /// draws the trailing line and `End` the leading one.
    pub fn alignment(mut self, alignment: MarkerAlignment) -> Self {
        self.alignment = Some(alignment);
        self
    }

    fn resolved_alignment(&self) -> MarkerAlignment {
        self.alignment.unwrap_or(match self.variant {
            MarkerVariant::Separator => MarkerAlignment::Center,
            MarkerVariant::Plain | MarkerVariant::Border => MarkerAlignment::Start,
        })
    }

    /// Set whether the marker should display its configured loading effect.
    pub fn loading(mut self, loading: bool) -> Self {
        self.loading = loading;
        self
    }

    /// Set the visual treatment used when [`Self::loading`] is enabled.
    pub fn with_loading_style(mut self, loading_style: MarkerLoadingStyle) -> Self {
        self.loading_style = loading_style;
        self
    }

    /// Configure the text highlight used by [`MarkerLoadingStyle::Shimmer`].
    pub fn with_shimmer_style(mut self, shimmer_style: ShimmerStyle) -> Self {
        self.shimmer_style = shimmer_style;
        self
    }

    /// Refine the decorative lines used by [`MarkerVariant::Separator`].
    pub fn separator_style(mut self, style: StyleRefinement) -> Self {
        self.separator_style = style;
        self
    }

    /// Add a configured icon slot.
    pub fn icon(mut self, icon: MarkerIcon) -> Self {
        self.children.push(MarkerChild::Icon(icon));
        self
    }

    /// Add a configured content slot.
    pub fn content(mut self, content: MarkerContent) -> Self {
        self.children.push(MarkerChild::Content(content));
        self
    }
}

impl Default for Marker {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for Marker {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children
            .extend(elements.into_iter().map(MarkerChild::Element));
    }
}

impl Styled for Marker {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Marker {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let tokens = cx.theme().semantic_tokens();
        let variant = self.variant;
        let alignment = self.resolved_alignment();
        let loading = self.loading;
        let loading_style = self.loading_style;
        let shimmer_style = self.shimmer_style;
        let has_icon = self
            .children
            .iter()
            .any(|child| matches!(child, MarkerChild::Icon(_)));
        let role = self.role;
        let separator_style = self.separator_style;
        let children = self.children.into_iter().map(move |child| match child {
            MarkerChild::Icon(icon) => icon.into_any_element(),
            MarkerChild::Content(mut content) => {
                content.shimmer = loading && loading_style == MarkerLoadingStyle::Shimmer;
                content.shimmer_style = shimmer_style;
                content.separator = variant == MarkerVariant::Separator;
                content.alignment = alignment;
                content.into_any_element()
            }
            MarkerChild::Element(element) => element,
        });

        let row = h_flex()
            .w_full()
            .min_h(rems(1.))
            .gap_2()
            .text_sm()
            .line_height(relative(1.5))
            .text_color(tokens.colors.muted_foreground)
            .map(|this| match alignment {
                MarkerAlignment::Start => this.justify_start().text_left(),
                MarkerAlignment::Center => this.justify_center().text_center(),
                MarkerAlignment::End => this.justify_end().text_right(),
            })
            .when(variant == MarkerVariant::Border, |this| {
                this.border_b_1().border_color(tokens.colors.border).pb_2()
            })
            .when(
                variant == MarkerVariant::Separator && alignment != MarkerAlignment::Start,
                |this| {
                    this.child(
                        div()
                            .flex_1()
                            .min_w_0()
                            .h(px(1.))
                            .mr_1()
                            .bg(tokens.colors.border)
                            .refine_style(&separator_style),
                    )
                },
            )
            .when(
                loading && loading_style == MarkerLoadingStyle::Spinner && !has_icon,
                |this| this.child(MarkerIcon::new().child(Spinner::new().xsmall())),
            )
            .children(children)
            .when(
                variant == MarkerVariant::Separator && alignment != MarkerAlignment::End,
                |this| {
                    this.child(
                        div()
                            .flex_1()
                            .min_w_0()
                            .h(px(1.))
                            .ml_1()
                            .bg(tokens.colors.border)
                            .refine_style(&separator_style),
                    )
                },
            )
            .refine_style(&self.style);

        // `role` lives on the stateful element: accessibility nodes need the
        // stable identity that only an element id provides.
        match (self.id, role) {
            (Some(id), RoleOverride::Role(role)) => row.id(id).role(role).into_any_element(),
            (Some(id), _) => row.id(id).into_any_element(),
            (None, _) => row.into_any_element(),
        }
    }
}

/// A compact decorative icon slot inside a [`Marker`].
#[derive(IntoElement)]
pub struct MarkerIcon {
    style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl MarkerIcon {
    /// Create an empty marker icon slot.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            children: Vec::new(),
        }
    }
}

impl Default for MarkerIcon {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for MarkerIcon {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for MarkerIcon {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for MarkerIcon {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        h_flex()
            .size_4()
            .flex_none()
            .items_center()
            .justify_center()
            .refine_style(&self.style)
            .children(self.children)
    }
}

/// The independently styleable text or rich-content slot in a [`Marker`].
#[derive(IntoElement)]
pub struct MarkerContent {
    style: StyleRefinement,
    shimmer: bool,
    shimmer_style: ShimmerStyle,
    separator: bool,
    alignment: MarkerAlignment,
    children: Vec<MarkerContentChild>,
}

enum MarkerContentChild {
    Text(SharedString),
    Element(AnyElement),
}

impl MarkerContent {
    /// Create an empty marker content slot.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            shimmer: false,
            shimmer_style: ShimmerStyle::default(),
            separator: false,
            alignment: MarkerAlignment::Start,
            children: Vec::new(),
        }
    }

    /// Add text that can receive a continuous loading shimmer.
    ///
    /// Arbitrary children remain supported through [`ParentElement`].
    pub fn text(mut self, text: impl Into<SharedString>) -> Self {
        self.children.push(MarkerContentChild::Text(text.into()));
        self
    }
}

impl Default for MarkerContent {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for MarkerContent {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children
            .extend(elements.into_iter().map(MarkerContentChild::Element));
    }
}

impl Styled for MarkerContent {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for MarkerContent {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let animate = self.shimmer && !cx.reduce_motion();
        let has_text = self
            .children
            .iter()
            .any(|child| matches!(child, MarkerContentChild::Text(_)));
        let base_opacity = self.style.opacity.unwrap_or(1.);
        let shimmer_style = self.shimmer_style;
        let children =
            self.children
                .into_iter()
                .enumerate()
                .map(move |(index, child)| match child {
                    MarkerContentChild::Text(text) if animate => ShimmerText::new(text)
                        .id(("marker-loading-text", index))
                        .with_shimmer_style(shimmer_style)
                        .into_any_element(),
                    MarkerContentChild::Text(text) => StyledText::new(text).into_any_element(),
                    MarkerContentChild::Element(element) => element,
                });

        let content = div()
            .min_w_0()
            // Between separator lines the label keeps its own width so the
            // lines take the rest; elsewhere it may shrink and wrap.
            .when(self.separator, |this| this.flex_none())
            .map(|this| match self.alignment {
                MarkerAlignment::Start => this.text_left(),
                MarkerAlignment::Center => this.text_center(),
                MarkerAlignment::End => this.text_right(),
            })
            .refine_style(&self.style)
            .children(children);

        if animate && !has_text {
            content
                .with_animation(
                    "marker-loading-content",
                    shimmer_style.animation(),
                    move |this, phase| {
                        let highlight = (phase * std::f32::consts::TAU).cos().mul_add(0.5, 0.5);
                        this.opacity(base_opacity * highlight.mul_add(0.4, 0.6))
                    },
                )
                .into_any_element()
        } else {
            content.into_any_element()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_marker_builder() {
        let marker = Marker::new()
            .with_variant(MarkerVariant::Separator)
            .loading(true)
            .with_loading_style(MarkerLoadingStyle::Shimmer)
            .with_shimmer_style(ShimmerStyle::new().reverse(true))
            .separator_style(StyleRefinement::default())
            .content(MarkerContent::new().child("Today"));

        assert_eq!(marker.variant, MarkerVariant::Separator);
        assert!(marker.loading);
        assert_eq!(marker.loading_style, MarkerLoadingStyle::Shimmer);
        assert_eq!(marker.children.len(), 1);
        assert_eq!(Marker::default().variant, MarkerVariant::Plain);
        assert!(Marker::default().alignment.is_none());
        assert!(!Marker::default().loading);
        assert_eq!(Marker::default().loading_style, MarkerLoadingStyle::Spinner);

        let centered = Marker::new().alignment(MarkerAlignment::Center);
        assert_eq!(centered.alignment, Some(MarkerAlignment::Center));

        let content_first = Marker::new()
            .content(MarkerContent::new().text("Thinking"))
            .with_loading_style(MarkerLoadingStyle::Shimmer)
            .loading(true);
        assert!(content_first.loading);
        assert_eq!(content_first.loading_style, MarkerLoadingStyle::Shimmer);
        assert!(matches!(
            &content_first.children[0],
            MarkerChild::Content(_)
        ));

        let custom_icon = Marker::new()
            .loading(true)
            .icon(MarkerIcon::new().child("custom"))
            .content(MarkerContent::new().text("Loading"));
        assert_eq!(custom_icon.children.len(), 2);
        assert!(matches!(&custom_icon.children[0], MarkerChild::Icon(_)));

        assert_eq!(Marker::default().role, RoleOverride::default());
        assert!(Marker::default().id.is_none());
        let status = Marker::new().id("sync-status").role(gpui::Role::Status);
        assert_eq!(status.id, Some("sync-status".into()));
        assert_eq!(status.role, RoleOverride::Role(gpui::Role::Status));

        let styled = Marker::new().opacity(0.37).child("Status").child("Details");

        assert_eq!(styled.style.opacity, Some(0.37));
        assert_eq!(styled.children.len(), 2);

        let icon = MarkerIcon::new().child("icon");
        assert_eq!(icon.children.len(), 1);

        let content = MarkerContent::new()
            .text("Thinking")
            .child("…")
            .text("正在思考");
        assert_eq!(content.children.len(), 3);
        assert!(matches!(&content.children[0], MarkerContentChild::Text(_)));
        assert!(matches!(
            &content.children[1],
            MarkerContentChild::Element(_)
        ));
        assert!(matches!(&content.children[2], MarkerContentChild::Text(_)));
    }

    #[test]
    fn test_marker_resolved_alignment() {
        // Unset: only the separator centers its label.
        assert_eq!(Marker::new().resolved_alignment(), MarkerAlignment::Start);
        assert_eq!(
            Marker::new()
                .with_variant(MarkerVariant::Border)
                .resolved_alignment(),
            MarkerAlignment::Start
        );
        assert_eq!(
            Marker::new()
                .with_variant(MarkerVariant::Separator)
                .resolved_alignment(),
            MarkerAlignment::Center
        );

        // Explicit alignment wins over the variant default, in either order.
        assert_eq!(
            Marker::new()
                .alignment(MarkerAlignment::End)
                .with_variant(MarkerVariant::Separator)
                .resolved_alignment(),
            MarkerAlignment::End
        );
        assert_eq!(
            Marker::new()
                .with_variant(MarkerVariant::Plain)
                .alignment(MarkerAlignment::Center)
                .resolved_alignment(),
            MarkerAlignment::Center
        );
    }
}
