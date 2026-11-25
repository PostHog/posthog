use gpui::{
    AnyElement, App, IntoElement, ParentElement, RenderOnce, StyleRefinement, Styled, Window, div,
    prelude::FluentBuilder as _, relative, rems,
};

use crate::{
    ActiveTheme as _, Colorize as _, StyledExt as _, button::Button, message::MessageAlignment,
    v_flex,
};

/// Visual treatment for a chat bubble.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum BubbleVariant {
    /// A filled primary surface.
    #[default]
    Filled,
    /// A neutral secondary surface.
    Secondary,
    /// A lower-emphasis surface.
    Muted,
    /// A subtle primary-tinted surface.
    Tinted,
    /// A background surface with a visible border.
    Outline,
    /// No surface, padding, or border.
    Ghost,
    /// A destructive surface for failed or invalid content.
    Destructive,
}

/// Edge on which reaction feedback is attached.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum BubbleReactionSide {
    /// Attach reactions above the bubble.
    Top,
    /// Attach reactions below the bubble.
    #[default]
    Bottom,
}

/// A chat bubble layout that owns alignment, width, and reaction positioning.
///
/// The visible surface is rendered by [`BubbleContent`]. Direct children are
/// added to that content slot as a convenience.
#[derive(IntoElement)]
pub struct Bubble {
    style: StyleRefinement,
    alignment: Option<MessageAlignment>,
    variant: BubbleVariant,
    content: BubbleContent,
    reactions: Option<BubbleReactions>,
}

impl Bubble {
    /// Create a filled bubble that can inherit alignment from its parent.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            alignment: None,
            variant: BubbleVariant::Filled,
            content: BubbleContent::new(),
            reactions: None,
        }
    }

    /// Set the bubble alignment.
    pub fn alignment(mut self, alignment: MessageAlignment) -> Self {
        self.alignment = Some(alignment);
        self
    }

    /// Set the visual treatment.
    pub fn with_variant(mut self, variant: BubbleVariant) -> Self {
        self.variant = variant;
        self
    }

    pub(crate) fn is_ghost(&self) -> bool {
        self.variant == BubbleVariant::Ghost
    }

    /// Replace the visible content surface.
    ///
    /// Children already added directly to the bubble move into the new
    /// surface, in front of its own children, so `.child(...)` composes the
    /// same way on either side of this call.
    pub fn content(mut self, mut content: BubbleContent) -> Self {
        let mut children = std::mem::take(&mut self.content.children);
        children.append(&mut content.children);
        content.children = children;
        self.content = content;
        self
    }

    /// Set an optional reaction region anchored to the bubble edge.
    pub fn reactions(mut self, reactions: BubbleReactions) -> Self {
        self.reactions = Some(reactions);
        self
    }
}

impl Default for Bubble {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for Bubble {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.content.children.extend(elements);
    }
}

impl Styled for Bubble {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Bubble {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let variant = self.variant;
        let mut content = self.content;
        content.variant = variant;
        content.alignment = self.alignment;

        div()
            .relative()
            .flex()
            .min_w_0()
            .flex_col()
            .flex_none()
            .gap_1()
            .max_w(relative(0.8))
            .when(variant == BubbleVariant::Ghost, |this| {
                this.w_full().max_w_full()
            })
            .when_some(self.alignment, |this, alignment| match alignment {
                MessageAlignment::Start => this.self_start().mr_auto(),
                MessageAlignment::End => this.self_end().ml_auto(),
            })
            .refine_style(&self.style)
            .child(content)
            .when_some(self.reactions, |this, reactions| this.child(reactions))
    }
}

/// The visible surface inside a [`Bubble`].
///
/// This part owns padding, radius, border, typography, and semantic colors so
/// callers can refine the surface without changing the bubble's row layout.
#[derive(IntoElement)]
pub struct BubbleContent {
    style: StyleRefinement,
    variant: BubbleVariant,
    alignment: Option<MessageAlignment>,
    children: Vec<AnyElement>,
}

impl BubbleContent {
    /// Create an empty bubble content surface.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            variant: BubbleVariant::default(),
            alignment: None,
            children: Vec::new(),
        }
    }
}

impl Default for BubbleContent {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for BubbleContent {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for BubbleContent {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for BubbleContent {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let tokens = cx.theme().semantic_tokens();

        div()
            .min_w_0()
            .max_w_full()
            // A ghost bubble has no surface to clip against; clipping would
            // only cut the shadows and overhanging controls of rich content.
            .when(self.variant != BubbleVariant::Ghost, |this| {
                this.overflow_hidden()
            })
            .rounded(cx.theme().radius_2xl())
            .border_1()
            .border_color(cx.theme().transparent)
            .px_3()
            .py_2()
            .text_sm()
            .line_height(relative(1.625))
            .when_some(self.alignment, |this, alignment| match alignment {
                MessageAlignment::Start => this.self_start(),
                MessageAlignment::End => this.self_end(),
            })
            .map(|this| match self.variant {
                BubbleVariant::Filled => this
                    .bg(tokens.colors.primary)
                    .text_color(tokens.colors.primary_foreground),
                // The theme's `secondary` role is tuned for buttons and sits a
                // tier darker than shadcn's conversation secondary; the
                // near-background `muted` tier matches shadcn's value in both
                // light and dark themes.
                BubbleVariant::Secondary => this
                    .bg(tokens.colors.muted)
                    .text_color(tokens.colors.secondary_foreground),
                BubbleVariant::Muted => this
                    .bg(tokens.colors.muted)
                    .text_color(tokens.colors.foreground),
                BubbleVariant::Tinted => this
                    .bg(tokens.colors.primary.mix_oklab(
                        tokens.colors.background,
                        if cx.theme().is_dark() { 0.24 } else { 0.12 },
                    ))
                    .text_color(tokens.colors.foreground),
                BubbleVariant::Outline => this
                    .border_color(tokens.colors.border)
                    .bg(tokens.colors.background)
                    .text_color(tokens.colors.foreground),
                BubbleVariant::Ghost => this
                    .rounded(tokens.radius.none)
                    .border_0()
                    .bg(cx.theme().transparent)
                    .text_color(tokens.colors.foreground)
                    .p_0(),
                BubbleVariant::Destructive => this
                    .bg(tokens.colors.destructive.opacity(if cx.theme().is_dark() {
                        0.2
                    } else {
                        0.1
                    }))
                    .text_color(tokens.colors.destructive),
            })
            .refine_style(&self.style)
            .children(self.children)
    }
}

/// A vertical stack of consecutive bubbles from one sender.
#[derive(IntoElement)]
pub struct BubbleGroup {
    style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl BubbleGroup {
    /// Create an empty bubble group.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            children: Vec::new(),
        }
    }
}

impl Default for BubbleGroup {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for BubbleGroup {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for BubbleGroup {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for BubbleGroup {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        v_flex()
            .min_w_0()
            .gap_2()
            .refine_style(&self.style)
            .children(self.children)
    }
}

enum BubbleReactionChild {
    Action(Box<Button>),
    Element(AnyElement),
}

/// A styleable reaction region positioned on a bubble edge.
///
/// Compose existing [`crate::button::Button`] values inside this region to
/// preserve button semantics and keyboard behavior.
#[derive(IntoElement)]
pub struct BubbleReactions {
    style: StyleRefinement,
    side: BubbleReactionSide,
    alignment: MessageAlignment,
    children: Vec<BubbleReactionChild>,
}

impl BubbleReactions {
    /// Create a trailing-aligned reaction region on the lower edge.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            side: BubbleReactionSide::Bottom,
            alignment: MessageAlignment::End,
            children: Vec::new(),
        }
    }

    /// Set the edge on which reactions are positioned.
    pub fn side(mut self, side: BubbleReactionSide) -> Self {
        self.side = side;
        self
    }

    /// Set the reaction region alignment along the bubble edge.
    pub fn alignment(mut self, alignment: MessageAlignment) -> Self {
        self.alignment = alignment;
        self
    }

    /// Add an interactive action that shares the reaction surface.
    ///
    /// Typed actions remove the reaction region's decorative content padding
    /// and use the theme's full radius so the button reads as part of one
    /// surface. The typed action owns that pill geometry; use `.child(...)`
    /// for emoji, labels, and arbitrary elements when the child should retain
    /// its own styling, including a custom button radius.
    pub fn action(mut self, action: Button) -> Self {
        self.children
            .push(BubbleReactionChild::Action(Box::new(action)));
        self
    }
}

impl Default for BubbleReactions {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for BubbleReactions {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children
            .extend(elements.into_iter().map(BubbleReactionChild::Element));
    }
}

impl Styled for BubbleReactions {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for BubbleReactions {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let tokens = cx.theme().semantic_tokens();
        let has_action = self
            .children
            .iter()
            .any(|child| matches!(child, BubbleReactionChild::Action(_)));
        let action_radius = cx.theme().radius_full();
        let children = self.children.into_iter().map(move |child| match child {
            BubbleReactionChild::Action(action) => {
                (*action).rounded(action_radius).into_any_element()
            }
            BubbleReactionChild::Element(element) => element,
        });

        div()
            .absolute()
            .flex()
            .flex_none()
            .items_center()
            .justify_center()
            .gap_1()
            .rounded(cx.theme().radius_full())
            .border_3()
            .border_color(tokens.colors.background)
            .bg(tokens.colors.muted)
            .text_color(tokens.colors.foreground)
            .when(!has_action, |this| this.px_1p5().py_0p5())
            .text_sm()
            // Approximates shadcn's `translate-y-3/4`: GPUI cannot offset by a
            // fraction of the pill's own height, so this fixed value leaves
            // about three quarters of the default pill outside the bubble.
            .when(self.side == BubbleReactionSide::Top, |this| {
                this.top(-rems(1.25))
            })
            .when(self.side == BubbleReactionSide::Bottom, |this| {
                this.bottom(-rems(1.25))
            })
            .when(self.alignment == MessageAlignment::Start, |this| {
                this.left_3()
            })
            .when(self.alignment == MessageAlignment::End, |this| {
                this.right_3()
            })
            .refine_style(&self.style)
            .children(children)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bubble_builder() {
        let bubble = Bubble::new()
            .alignment(MessageAlignment::End)
            .with_variant(BubbleVariant::Outline)
            .content(BubbleContent::new().child("Hello"))
            .reactions(BubbleReactions::new().child("👍"));

        assert_eq!(bubble.alignment, Some(MessageAlignment::End));
        assert_eq!(bubble.variant, BubbleVariant::Outline);
        assert_eq!(bubble.content.children.len(), 1);
        assert!(bubble.reactions.is_some());

        // Direct children survive a later `content(...)` call and stay in
        // front of the new surface's own children.
        let reordered = Bubble::new()
            .child("Existing")
            .content(BubbleContent::new().child("Configured"));
        assert_eq!(reordered.content.children.len(), 2);

        let group = BubbleGroup::new().child("First").child("Second");
        assert_eq!(group.children.len(), 2);

        let reactions = BubbleReactions::new()
            .side(BubbleReactionSide::Top)
            .alignment(MessageAlignment::Start)
            .child("👍 2");

        assert_eq!(reactions.side, BubbleReactionSide::Top);
        assert_eq!(reactions.alignment, MessageAlignment::Start);
        assert_eq!(reactions.children.len(), 1);

        let reactions = BubbleReactions::new()
            .action(Button::new("reaction-action"))
            .child("👍");
        assert_eq!(reactions.children.len(), 2);
        assert!(matches!(
            reactions.children.first(),
            Some(BubbleReactionChild::Action(_))
        ));
        assert!(matches!(
            reactions.children.get(1),
            Some(BubbleReactionChild::Element(_))
        ));
    }
}
