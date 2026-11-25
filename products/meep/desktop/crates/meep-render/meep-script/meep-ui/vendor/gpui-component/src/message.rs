use gpui::{
    AnyElement, App, ElementId, InteractiveElement as _, IntoElement, ParentElement, RenderOnce,
    StatefulInteractiveElement as _, StyleRefinement, Styled, Window, prelude::FluentBuilder as _,
    relative, rems,
};

use crate::{ActiveTheme as _, RoleOverride, StyledExt as _, bubble::Bubble, h_flex, v_flex};

/// Horizontal alignment for a message and message-owned chat surfaces.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum MessageAlignment {
    /// Place the message at the leading edge.
    #[default]
    Start,
    /// Place the message at the trailing edge.
    End,
}

/// A vertical stack of consecutive messages from the same sender.
#[derive(IntoElement)]
pub struct MessageGroup {
    style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl MessageGroup {
    /// Create an empty message group.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            children: Vec::new(),
        }
    }
}

impl Default for MessageGroup {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for MessageGroup {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for MessageGroup {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for MessageGroup {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        v_flex()
            .min_w_0()
            .gap_2()
            .refine_style(&self.style)
            .children(self.children)
    }
}

/// A composable message row with named avatar, header, content, and footer slots.
///
/// Named slots let the message apply its alignment consistently while every
/// part remains independently styleable.
#[derive(IntoElement)]
pub struct Message {
    id: Option<ElementId>,
    role: RoleOverride,
    style: StyleRefinement,
    stack_style: StyleRefinement,
    alignment: MessageAlignment,
    avatar: Option<MessageAvatar>,
    header: Option<MessageHeader>,
    content: Option<MessageContent>,
    footer: Option<MessageFooter>,
}

impl Message {
    /// Create a leading-aligned message.
    pub fn new() -> Self {
        Self {
            id: None,
            role: RoleOverride::default(),
            style: StyleRefinement::default(),
            stack_style: StyleRefinement::default(),
            alignment: MessageAlignment::Start,
            avatar: None,
            header: None,
            content: None,
            footer: None,
        }
    }

    /// Set whether the message is aligned to the leading or trailing edge.
    pub fn alignment(mut self, alignment: MessageAlignment) -> Self {
        self.alignment = alignment;
        self
    }

    /// Set a stable identity so the message can appear in the accessibility
    /// tree and keep element state across frames.
    pub fn id(mut self, id: impl Into<ElementId>) -> Self {
        self.id = Some(id.into());
        self
    }

    /// Set the accessibility role announced for this message.
    ///
    /// A message is presentational by default. Give the rows of a transcript
    /// a role such as [`gpui::Role::ListItem`] so assistive technology can
    /// move between them. Accessibility nodes need a stable identity, so the
    /// role takes effect only together with [`Self::id`].
    pub fn role(mut self, role: impl Into<RoleOverride>) -> Self {
        self.role = role.into();
        self
    }

    /// Refine the inner vertical stack that contains the named slots.
    pub fn with_stack_style(mut self, style: StyleRefinement) -> Self {
        self.stack_style = style;
        self
    }

    /// Set an optional avatar or other sender identity element.
    pub fn avatar(mut self, avatar: impl IntoElement) -> Self {
        self.avatar = Some(MessageAvatar::new().child(avatar));
        self
    }

    /// Set a fully configured avatar slot.
    pub fn avatar_slot(mut self, avatar: MessageAvatar) -> Self {
        self.avatar = Some(avatar);
        self
    }

    /// Set the message header.
    pub fn header(mut self, header: MessageHeader) -> Self {
        self.header = Some(header);
        self
    }

    /// Set the message body.
    pub fn content(mut self, content: MessageContent) -> Self {
        self.content = Some(content);
        self
    }

    /// Set the message footer.
    pub fn footer(mut self, footer: MessageFooter) -> Self {
        self.footer = Some(footer);
        self
    }
}

impl Default for Message {
    fn default() -> Self {
        Self::new()
    }
}

impl Styled for Message {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Message {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let alignment = self.alignment;
        let has_avatar = self.avatar.is_some();
        let has_ghost_bubble = self
            .content
            .as_ref()
            .is_some_and(|content| content.has_ghost_bubble);
        let stack_style = self.stack_style;
        let role = self.role;

        // No text size or line height here: the header and footer set their
        // own, and content typography belongs to the bubble or the caller.
        let row = v_flex()
            .relative()
            .w_full()
            .min_w_0()
            .gap(rems(0.625))
            .map(|this| match alignment {
                MessageAlignment::Start => this.items_start(),
                MessageAlignment::End => this.items_end(),
            })
            .refine_style(&self.style)
            .child(
                // The footer lives outside this row so the bottom-anchored
                // avatar always sits flush with the content's bottom edge,
                // whatever the footer contains.
                h_flex()
                    .w_full()
                    .min_w_0()
                    .items_end()
                    .gap_2()
                    .when(alignment == MessageAlignment::End, |this| {
                        this.flex_row_reverse()
                    })
                    .when_some(self.avatar, |this, avatar| this.child(avatar))
                    .child(
                        v_flex()
                            .w_full()
                            .min_w_0()
                            .gap(rems(0.625))
                            .map(|this| match alignment {
                                MessageAlignment::Start => this.items_start(),
                                MessageAlignment::End => this.items_end(),
                            })
                            .refine_style(&stack_style)
                            .when_some(self.header, |this, header| {
                                this.child(header.with_inherited_content_inset(!has_ghost_bubble))
                            })
                            .when_some(self.content, |this, content| {
                                this.child(content.aligned(alignment))
                            }),
                    ),
            )
            .when_some(self.footer, |this, footer| {
                this.child(
                    footer
                        .with_inherited_content_inset(!has_ghost_bubble)
                        // Align the footer with the content column: the
                        // avatar's shared `size-8` baseline plus the row gap.
                        .when(has_avatar && alignment == MessageAlignment::Start, |this| {
                            this.ml(rems(2.5))
                        })
                        .when(has_avatar && alignment == MessageAlignment::End, |this| {
                            this.mr(rems(2.5))
                        }),
                )
            });

        // `role` lives on the stateful element: accessibility nodes need the
        // stable identity that only an element id provides.
        match (self.id, role) {
            (Some(id), RoleOverride::Role(role)) => row.id(id).role(role).into_any_element(),
            (Some(id), _) => row.id(id).into_any_element(),
            (None, _) => row.into_any_element(),
        }
    }
}

/// The sender identity slot rendered beside a [`Message`].
///
/// The slot reserves the shared `size-8` baseline; the message row keeps it
/// flush with the bottom edge of the visible message surface.
#[derive(IntoElement)]
pub struct MessageAvatar {
    style: StyleRefinement,
    children: Vec<AnyElement>,
}

impl MessageAvatar {
    /// Create an empty avatar slot.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            children: Vec::new(),
        }
    }
}

impl Default for MessageAvatar {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for MessageAvatar {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for MessageAvatar {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for MessageAvatar {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let tokens = cx.theme().semantic_tokens();

        h_flex()
            .relative()
            .min_w_8()
            .flex_none()
            .items_center()
            .justify_center()
            .self_end()
            .overflow_hidden()
            .rounded(cx.theme().radius_full())
            .bg(tokens.colors.muted)
            .refine_style(&self.style)
            .children(self.children)
    }
}

/// Header content such as a sender name and timestamp.
#[derive(IntoElement)]
pub struct MessageHeader {
    style: StyleRefinement,
    content_inset: Option<bool>,
    children: Vec<AnyElement>,
}

impl MessageHeader {
    /// Create an empty message header.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            content_inset: None,
            children: Vec::new(),
        }
    }

    /// Set whether the header keeps its default horizontal content inset.
    pub fn content_inset(mut self, content_inset: bool) -> Self {
        self.content_inset = Some(content_inset);
        self
    }

    fn with_inherited_content_inset(mut self, content_inset: bool) -> Self {
        self.content_inset.get_or_insert(content_inset);
        self
    }
}

impl Default for MessageHeader {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for MessageHeader {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for MessageHeader {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for MessageHeader {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let tokens = cx.theme().semantic_tokens();

        h_flex()
            .max_w_full()
            .min_w_0()
            .gap_1()
            .text_xs()
            .line_height(relative(1.25))
            .font_medium()
            .text_color(tokens.colors.muted_foreground)
            .when(self.content_inset.unwrap_or(true), |this| this.px_3())
            .refine_style(&self.style)
            .children(self.children)
    }
}

/// The message body slot. It can contain bubbles, images, code, or files.
#[derive(IntoElement)]
pub struct MessageContent {
    style: StyleRefinement,
    alignment: MessageAlignment,
    has_ghost_bubble: bool,
    children: Vec<AnyElement>,
}

impl MessageContent {
    /// Create an empty message body.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            alignment: MessageAlignment::Start,
            has_ghost_bubble: false,
            children: Vec::new(),
        }
    }

    /// Add a typed bubble and inherit ghost-surface metadata layout.
    ///
    /// Ordinary `.child(...)` content remains available for arbitrary elements;
    /// use this builder when surrounding message slots should react to a
    /// bubble's variant.
    pub fn bubble(mut self, bubble: Bubble) -> Self {
        self.has_ghost_bubble |= bubble.is_ghost();
        self.children.push(bubble.into_any_element());
        self
    }

    fn aligned(mut self, alignment: MessageAlignment) -> Self {
        self.alignment = alignment;
        self
    }
}

impl Default for MessageContent {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for MessageContent {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for MessageContent {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for MessageContent {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        v_flex()
            .w_full()
            .max_w_full()
            .min_w_0()
            .gap(rems(0.625))
            .map(|this| match self.alignment {
                MessageAlignment::Start => this.items_start(),
                MessageAlignment::End => this.items_end(),
            })
            .refine_style(&self.style)
            .children(self.children)
    }
}

/// Footer content such as delivery state, reactions, or action buttons.
#[derive(IntoElement)]
pub struct MessageFooter {
    style: StyleRefinement,
    content_inset: Option<bool>,
    children: Vec<AnyElement>,
}

impl MessageFooter {
    /// Create an empty message footer.
    pub fn new() -> Self {
        Self {
            style: StyleRefinement::default(),
            content_inset: None,
            children: Vec::new(),
        }
    }

    /// Set whether the footer keeps its default horizontal content inset.
    pub fn content_inset(mut self, content_inset: bool) -> Self {
        self.content_inset = Some(content_inset);
        self
    }

    fn with_inherited_content_inset(mut self, content_inset: bool) -> Self {
        self.content_inset.get_or_insert(content_inset);
        self
    }
}

impl Default for MessageFooter {
    fn default() -> Self {
        Self::new()
    }
}

impl ParentElement for MessageFooter {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children.extend(elements);
    }
}

impl Styled for MessageFooter {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for MessageFooter {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let tokens = cx.theme().semantic_tokens();

        h_flex()
            .max_w_full()
            .min_w_0()
            .gap_1()
            .text_xs()
            .line_height(relative(1.25))
            .font_medium()
            .text_color(tokens.colors.muted_foreground)
            .when(self.content_inset.unwrap_or(true), |this| this.px_3())
            .refine_style(&self.style)
            .children(self.children)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_message_builder() {
        let stack_style = StyleRefinement::default().gap_1();
        let message = Message::new()
            .alignment(MessageAlignment::End)
            .with_stack_style(stack_style.clone())
            .avatar_slot(MessageAvatar::new().child(gpui::div()))
            .header(MessageHeader::new().content_inset(false).child("Alice"))
            .content(MessageContent::new().child("Hello"))
            .footer(MessageFooter::new().content_inset(false).child("Delivered"));

        assert_eq!(message.alignment, MessageAlignment::End);
        assert_eq!(message.stack_style, stack_style);
        assert!(message.avatar.is_some());
        assert!(message.header.is_some());
        assert!(message.content.is_some());
        assert!(message.footer.is_some());
        assert_eq!(message.header.as_ref().unwrap().content_inset, Some(false));
        assert_eq!(message.footer.as_ref().unwrap().content_inset, Some(false));
        assert!(message.id.is_none());
        assert_eq!(message.role, RoleOverride::default());

        let row = Message::new().id("message-1").role(gpui::Role::ListItem);
        assert_eq!(row.id, Some("message-1".into()));
        assert_eq!(row.role, RoleOverride::Role(gpui::Role::ListItem));

        let group = MessageGroup::new().child("First").child("Second");
        assert_eq!(group.children.len(), 2);

        let content = MessageContent::new().aligned(MessageAlignment::End);
        assert_eq!(content.alignment, MessageAlignment::End);

        let avatar = MessageAvatar::new().child("ME");
        assert_eq!(avatar.children.len(), 1);
    }

    #[test]
    fn test_ghost_bubble_inherits_message_slot_insets() {
        let content = MessageContent::new()
            .bubble(Bubble::new())
            .bubble(Bubble::new().with_variant(crate::bubble::BubbleVariant::Ghost));

        assert!(content.has_ghost_bubble);
        assert_eq!(content.children.len(), 2);
        assert_eq!(
            MessageHeader::new()
                .with_inherited_content_inset(false)
                .content_inset,
            Some(false)
        );
        assert_eq!(
            MessageFooter::new()
                .with_inherited_content_inset(false)
                .content_inset,
            Some(false)
        );
        assert_eq!(
            MessageHeader::new()
                .content_inset(true)
                .with_inherited_content_inset(false)
                .content_inset,
            Some(true)
        );
        assert_eq!(
            MessageFooter::new()
                .content_inset(true)
                .with_inherited_content_inset(false)
                .content_inset,
            Some(true)
        );
    }
}
