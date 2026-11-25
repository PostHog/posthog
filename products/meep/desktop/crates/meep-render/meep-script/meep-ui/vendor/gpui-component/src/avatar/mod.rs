mod avatar;
mod avatar_group;

pub use avatar::*;
pub use avatar_group::*;

use crate::{Icon, Size, StyledExt as _};
use gpui::{Div, Img, IntoElement, Pixels, Styled, px, rems};

/// Returns the size of the avatar based on the given [`Size`].
pub(super) fn avatar_size(size: Size) -> Pixels {
    match size {
        Size::Large => px(80.),
        Size::Medium => px(48.),
        Size::Small => px(24.),
        Size::XSmall => px(16.),
        Size::Size(size) => size,
    }
}

/// Extension for add `avatar_size` method to `IntoElement` to apply avatar size to element.
pub(super) trait AvatarSized: IntoElement + Styled {
    fn avatar_text_size(self, size: Size) -> Self {
        match size {
            Size::Large => self.text_3xl().font_semibold(),
            Size::Medium => self.text_sm(),
            Size::Small => self.text_xs(),
            Size::XSmall => self.text_size(rems(0.65)),
            Size::Size(size) => self.size(size * 0.5),
        }
    }
}
impl AvatarSized for Div {}
impl AvatarSized for Icon {}
impl AvatarSized for Img {}
