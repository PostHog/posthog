use gpui::{
    AnyElement, App, ElementId, IntoElement, ParentElement, RenderOnce, SharedString,
    StyleRefinement, Styled, Window, div, prelude::FluentBuilder as _,
};
use smallvec::SmallVec;

use gpui_base::{Toolbar as BaseToolbar, ToolbarGroup as BaseToolbarGroup};

use crate::{Sizable, Size, StyleSized as _, StyledExt as _};

enum ToolbarItem {
    Sized(Box<dyn FnOnce(Size) -> AnyElement>),
    Content(AnyElement),
}

impl ToolbarItem {
    fn sized(item: impl Sizable + IntoElement + 'static) -> Self {
        Self::Sized(Box::new(move |size| {
            item.prepare_for_toolbar()
                .with_size(size)
                .into_any_element()
        }))
    }

    fn content(content: impl IntoElement) -> Self {
        Self::Content(content.into_any_element())
    }

    fn into_element(self, size: Size) -> AnyElement {
        match self {
            Self::Sized(item) => div()
                .flex()
                .items_center()
                .input_h(size)
                .child(item(size))
                .into_any_element(),
            Self::Content(content) => content,
        }
    }
}

/// A semantic subgroup of toolbar controls that shares one accessible label
/// and propagates its size to every control added with `child` or `children`.
#[derive(IntoElement)]
pub struct ToolbarGroup {
    id: ElementId,
    style: StyleRefinement,
    size: Size,
    label: Option<SharedString>,
    children: SmallVec<[ToolbarItem; 4]>,
}

impl ToolbarGroup {
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            size: Size::Small,
            label: None,
            children: SmallVec::new(),
        }
    }

    /// Sets the accessible name announced for the group.
    pub fn label(mut self, label: impl Into<SharedString>) -> Self {
        self.label = Some(label.into());
        self
    }

    /// Append a control that inherits the group's final size.
    pub fn child(mut self, child: impl Sizable + IntoElement + 'static) -> Self {
        self.children.push(ToolbarItem::sized(child));
        self
    }

    /// Append controls that inherit the group's final size.
    pub fn children<T>(mut self, children: impl IntoIterator<Item = T>) -> Self
    where
        T: Sizable + IntoElement + 'static,
    {
        self.children
            .extend(children.into_iter().map(ToolbarItem::sized));
        self
    }

    /// Append non-sized content to the group.
    pub fn content(mut self, content: impl IntoElement) -> Self {
        self.children.push(ToolbarItem::content(content));
        self
    }
}

impl ParentElement for ToolbarGroup {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.children
            .extend(elements.into_iter().map(ToolbarItem::Content));
    }
}

impl Styled for ToolbarGroup {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Sizable for ToolbarGroup {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = match size.into() {
            Size::Large => Size::Medium,
            size => size,
        };
        self
    }
}

impl RenderOnce for ToolbarGroup {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let size = self.size;
        BaseToolbarGroup::new(self.id)
            .when_some(self.label, |this, label| this.label(label))
            .children(
                self.children
                    .into_iter()
                    .map(|item| item.into_element(size)),
            )
            .refine_style(&self.style)
    }
}

/// A transparent horizontal container for commands in a window, pane, or
/// section.
///
/// The toolbar owns layout and keyboard behavior while the surrounding header,
/// tab strip, or custom surface owns its background and border.
///
/// The bar exposes `Toolbar` semantics to assistive technology and owns
/// roving keyboard focus: when focus is on one of its controls, the arrow
/// keys move focus along the bar, wrapping around at the ends. Hosted inputs
/// keep their own arrow-key caret behavior; place them at the trailing end of
/// the bar.
///
/// `child` accepts [`Sizable`] controls and automatically applies the toolbar's
/// final size, regardless of builder order. Use `content` for separators,
/// labels, flexible spacers, and custom layout. Items render in source order,
/// matching Base UI's toolbar composition model. An icon-only button must
/// carry a tooltip and an accessible name.
///
/// The id keeps the toolbar's keyboard-focus state stable across frames;
/// give each toolbar in a window a distinct id.
///
/// ```
/// # mod gpui_kit { pub extern crate gpui_component as component; }
/// use gpui_kit::component::toolbar::Toolbar;
///
/// let _ = Toolbar::new("document-toolbar").content("Document");
/// ```
#[derive(IntoElement)]
pub struct Toolbar {
    id: ElementId,
    style: StyleRefinement,
    size: Size,
    disabled: bool,
    items: SmallVec<[ToolbarItem; 4]>,
}

impl Toolbar {
    /// Create a new, empty [`Toolbar`] at [`Size::Small`].
    pub fn new(id: impl Into<ElementId>) -> Self {
        Self {
            id: id.into(),
            style: StyleRefinement::default(),
            size: Size::Small,
            disabled: false,
            items: SmallVec::new(),
        }
    }

    /// Disable the toolbar's roving keyboard navigation.
    /// Hosted controls must be disabled by their owner.
    pub fn disabled(mut self, disabled: bool) -> Self {
        self.disabled = disabled;
        self
    }

    /// Append a sized control. The toolbar applies its
    /// final size when it renders, so builder call order does not matter.
    pub fn child(mut self, child: impl Sizable + IntoElement + 'static) -> Self {
        self.items.push(ToolbarItem::sized(child));
        self
    }

    /// Append sized controls.
    pub fn children<T>(mut self, children: impl IntoIterator<Item = T>) -> Self
    where
        T: Sizable + IntoElement + 'static,
    {
        self.items
            .extend(children.into_iter().map(ToolbarItem::sized));
        self
    }

    /// Append non-sized content.
    pub fn content(mut self, content: impl IntoElement) -> Self {
        self.items.push(ToolbarItem::content(content));
        self
    }

    /// Append non-sized content.
    pub fn contents(mut self, contents: impl IntoIterator<Item = AnyElement>) -> Self {
        self.items
            .extend(contents.into_iter().map(ToolbarItem::Content));
        self
    }
}

/// Generic [`ParentElement`] extension treats elements as non-sized content.
/// Prefer the inherent `child` / `children` methods for controls that should
/// inherit the toolbar size.
impl ParentElement for Toolbar {
    fn extend(&mut self, elements: impl IntoIterator<Item = AnyElement>) {
        self.items
            .extend(elements.into_iter().map(ToolbarItem::Content));
    }
}

impl Styled for Toolbar {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

impl Sizable for Toolbar {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = match size.into() {
            Size::Large => Size::Medium,
            size => size,
        };
        self
    }
}

impl RenderOnce for Toolbar {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        let size = self.size;
        let items = self.items.into_iter().map(|item| item.into_element(size));

        BaseToolbar::new(self.id)
            .disabled(self.disabled)
            .flex()
            .items_center()
            .flex_shrink_0()
            .map(|this| match size {
                Size::XSmall => this.min_h_7().p_1().gap_1().text_xs(),
                Size::Small => this.min_h_8().p_1().gap_1().text_sm(),
                _ => this.min_h_12().p_2().gap_2().text_sm(),
            })
            .refine_style(&self.style)
            .children(items)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::button::{Button, ButtonVariant};
    use gpui::{Context, Render, TestAppContext, div};
    use std::sync::{Arc, Mutex};

    #[derive(IntoElement)]
    struct SizeProbe {
        size: Size,
        observed: Arc<Mutex<Option<Size>>>,
    }

    impl SizeProbe {
        fn new(observed: Arc<Mutex<Option<Size>>>) -> Self {
            Self {
                size: Size::default(),
                observed,
            }
        }
    }

    impl Sizable for SizeProbe {
        fn with_size(mut self, size: impl Into<Size>) -> Self {
            self.size = size.into();
            self
        }
    }

    impl RenderOnce for SizeProbe {
        fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
            *self.observed.lock().unwrap() = Some(self.size);
            div()
        }
    }

    struct ToolbarHarness {
        items: [Arc<Mutex<Option<Size>>>; 3],
    }

    struct ToolbarGroupHarness {
        item: Arc<Mutex<Option<Size>>>,
    }

    impl Render for ToolbarGroupHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            ToolbarGroup::new("group")
                .child(SizeProbe::new(self.item.clone()))
                .small()
        }
    }

    impl Render for ToolbarHarness {
        fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
            Toolbar::new("toolbar")
                .children(self.items.iter().cloned().map(SizeProbe::new))
                .small()
        }
    }

    #[test]
    fn test_toolbar_builder() {
        let toolbar = Toolbar::new("toolbar")
            .content("New")
            .content("Open")
            .content("Settings")
            .small();

        assert_eq!(toolbar.items.len(), 3);
        assert_eq!(toolbar.size, Size::Small);
    }

    #[test]
    fn test_toolbar_default() {
        let toolbar = Toolbar::new("toolbar");

        assert_eq!(toolbar.size, Size::Small);
        assert!(!toolbar.disabled);
        assert!(toolbar.items.is_empty());
    }

    #[test]
    fn large_size_falls_back_to_medium() {
        assert_eq!(Toolbar::new("toolbar").large().size, Size::Medium);
        assert_eq!(ToolbarGroup::new("group").large().size, Size::Medium);
    }

    #[test]
    fn toolbar_prepares_buttons_as_compact_ghost_commands() {
        let button = Button::new("command").prepare_for_toolbar();

        assert_eq!(button.variant(), ButtonVariant::Ghost);
        assert!(button.is_compact());
    }

    #[gpui::test]
    fn toolbar_size_propagates_to_items_independent_of_builder_order(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let expected = std::array::from_fn(|_| Arc::new(Mutex::new(None)));
        let items = expected.clone();
        let (_, cx) = cx.add_window_view(move |_, _| ToolbarHarness { items });
        cx.update(|window, cx| window.draw(cx).clear(cx));

        for observed in expected {
            assert_eq!(*observed.lock().unwrap(), Some(Size::Small));
        }
    }

    #[gpui::test]
    fn toolbar_group_propagates_its_size_to_items(cx: &mut TestAppContext) {
        let item = Arc::new(Mutex::new(None));
        let observed = item.clone();
        let (_, cx) = cx.add_window_view(move |_, _| ToolbarGroupHarness { item });
        cx.update(|window, cx| window.draw(cx).clear(cx));

        assert_eq!(*observed.lock().unwrap(), Some(Size::Small));
    }
}
