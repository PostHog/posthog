use gpui::{AnyElement, IntoElement};

pub use gpui_base::ElementExt;

use crate::{Sizable, Size};

#[derive(Default)]
struct ChildElementOptions {
    ix: usize,
    size: Size,
}

#[allow(patterns_in_fns_without_body)]
pub trait ChildElement: Sizable + IntoElement {
    fn with_ix(mut self, ix: usize) -> Self;
}

/// A type-erased element that can accept a [`AnyChildElementOptions`] before being rendered.
pub struct AnyChildElement(Box<dyn FnOnce(ChildElementOptions) -> AnyElement>);

impl AnyChildElement {
    pub fn new(element: impl ChildElement + 'static) -> Self {
        Self(Box::new(|options| {
            element
                .with_ix(options.ix)
                .with_size(options.size)
                .into_any_element()
        }))
    }

    pub fn into_any(self, ix: usize, size: Size) -> AnyElement {
        (self.0)(ChildElementOptions { ix, size })
    }
}
