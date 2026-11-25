use gpui::{
    Div, InteractiveElement, Interactivity, IntoElement, ParentElement as _, RenderOnce,
    StyleRefinement, Styled, div, prelude::FluentBuilder as _,
};

use crate::{ActiveTheme, Sizable, Size, StyledExt as _, avatar::Avatar};

/// A grouped avatars to display in a compact layout.
#[derive(IntoElement)]
pub struct AvatarGroup {
    base: Div,
    style: StyleRefinement,
    avatars: Vec<Avatar>,
    size: Size,
    limit: usize,
    ellipsis: bool,
}

impl AvatarGroup {
    /// Create a new AvatarGroup.
    pub fn new() -> Self {
        Self {
            base: div(),
            style: StyleRefinement::default(),
            avatars: Vec::new(),
            size: Size::default(),
            limit: 3,
            ellipsis: false,
        }
    }

    /// Add a child avatar to the group.
    pub fn child(mut self, avatar: Avatar) -> Self {
        self.avatars.push(avatar);
        self
    }

    /// Add multiple child avatars to the group.
    pub fn children(mut self, avatars: impl IntoIterator<Item = Avatar>) -> Self {
        self.avatars.extend(avatars);
        self
    }

    /// Set the maximum number of avatars to display before showing a "more" avatar.
    pub fn limit(mut self, limit: usize) -> Self {
        self.limit = limit;
        self
    }

    /// Set whether to show an ellipsis when the limit is reached, default: false
    pub fn ellipsis(mut self) -> Self {
        self.ellipsis = true;
        self
    }
}

impl Sizable for AvatarGroup {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = size.into();
        self
    }
}

impl Styled for AvatarGroup {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl InteractiveElement for AvatarGroup {
    fn interactivity(&mut self) -> &mut Interactivity {
        self.base.interactivity()
    }
}

impl RenderOnce for AvatarGroup {
    fn render(self, _: &mut gpui::Window, cx: &mut gpui::App) -> impl IntoElement {
        let item_ml = -super::avatar_size(self.size) * 0.3;
        let avatars_len = self.avatars.len();

        self.base
            .h_flex()
            .flex_row_reverse()
            .refine_style(&self.style)
            .children(if self.ellipsis && avatars_len > self.limit {
                Some(
                    Avatar::new()
                        .name("⋯")
                        .bg(cx.theme().tokens.secondary)
                        .text_color(cx.theme().muted_foreground)
                        .with_size(self.size)
                        .ml_1(),
                )
            } else {
                None
            })
            .children(
                self.avatars
                    .into_iter()
                    .take(self.limit)
                    .enumerate()
                    .rev()
                    .map(|(ix, item)| {
                        item.with_size(self.size)
                            .when(ix > 0, |this| this.ml(item_ml))
                    }),
            )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[gpui::test]
    fn test_avatar_group_builder(_cx: &mut gpui::TestAppContext) {
        let group = AvatarGroup::new()
            .child(Avatar::new().name("Alice"))
            .child(Avatar::new().name("Bob"))
            .child(Avatar::new().name("Charlie"))
            .child(Avatar::new().name("David"))
            .large()
            .limit(3)
            .ellipsis();

        assert_eq!(group.avatars.len(), 4);
        assert_eq!(group.size, Size::Large);
        assert_eq!(group.limit, 3);
        assert!(group.ellipsis);
    }
}
