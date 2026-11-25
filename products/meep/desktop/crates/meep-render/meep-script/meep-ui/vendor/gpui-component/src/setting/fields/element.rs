use gpui::{AnyElement, App, IntoElement, StyleRefinement, Window};
use std::rc::Rc;

use crate::setting::{AnySettingField, RenderOptions, fields::SettingFieldRender};

/// A trait for rendering custom setting field elements.
///
/// For [`crate::setting::SettingField::element`] method.
pub trait SettingFieldElement {
    type Element: IntoElement + 'static;

    fn render_field(
        &self,
        options: &RenderOptions,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::Element;
}

impl<F, E> SettingFieldElement for F
where
    E: IntoElement + 'static,
    F: Fn(&RenderOptions, &mut Window, &mut App) -> E,
{
    type Element = E;

    fn render_field(
        &self,
        options: &RenderOptions,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::Element {
        (self)(options, window, cx)
    }
}

pub(crate) struct AnySettingFieldElement<T>(pub(crate) T);
impl<T> SettingFieldElement for AnySettingFieldElement<T>
where
    T: SettingFieldElement,
{
    type Element = AnyElement;

    fn render_field(
        &self,
        options: &RenderOptions,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::Element {
        self.0.render_field(options, window, cx).into_any_element()
    }
}
impl SettingFieldElement for Rc<dyn SettingFieldElement<Element = AnyElement>> {
    type Element = AnyElement;

    fn render_field(
        &self,
        options: &RenderOptions,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::Element {
        self.as_ref().render_field(options, window, cx)
    }
}

pub(crate) struct ElementField {
    element_render: Rc<dyn SettingFieldElement<Element = AnyElement>>,
}

impl ElementField {
    pub(crate) fn new<E>(element_render: E) -> Self
    where
        E: SettingFieldElement<Element = AnyElement> + 'static,
    {
        Self {
            element_render: Rc::new(element_render),
        }
    }
}

impl SettingFieldRender for ElementField {
    fn render(
        &self,
        _: Rc<dyn AnySettingField>,
        options: &RenderOptions,
        _style: &StyleRefinement,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement {
        (self.element_render).render_field(options, window, cx)
    }
}
