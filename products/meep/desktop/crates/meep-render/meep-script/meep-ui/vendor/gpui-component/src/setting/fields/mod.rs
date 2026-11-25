mod bool;
mod dropdown;
mod element;
mod number;
mod string;

pub(crate) use bool::*;
pub(crate) use dropdown::*;
pub(crate) use element::*;
pub(crate) use number::*;
pub(crate) use string::*;

pub use element::SettingFieldElement;
pub use number::NumberFieldOptions;

use gpui::{AnyElement, App, IntoElement, SharedString, StyleRefinement, Styled, Window};
use std::{any::Any, rc::Rc};

use crate::setting::RenderOptions;

/// Custom reset behavior for a setting field or item.
///
/// The first closure reports whether the target is "dirty" (controls the reset
/// button visibility), the second performs the reset. Used by `element`/`render`
/// fields and custom element items whose state is not expressed through the
/// typed `default_value` mechanism.
pub(crate) type ResetHandler = (Rc<dyn Fn(&App) -> bool>, Rc<dyn Fn(&mut Window, &mut App)>);

pub(crate) trait SettingFieldRender {
    #[allow(clippy::too_many_arguments)]
    fn render(
        &self,
        field: Rc<dyn AnySettingField>,
        options: &RenderOptions,
        style: &StyleRefinement,
        window: &mut Window,
        cx: &mut App,
    ) -> AnyElement;
}

pub(crate) fn get_value<T: Clone + 'static>(field: &Rc<dyn AnySettingField>, cx: &mut App) -> T {
    let setting_field = field
        .as_any()
        .downcast_ref::<SettingField<T>>()
        .expect("Failed to downcast setting field");
    (setting_field.value)(cx)
}

pub(crate) fn set_value<T: Clone + 'static>(
    field: &Rc<dyn AnySettingField>,
    _cx: &mut App,
) -> Rc<dyn Fn(T, &mut App)> {
    let setting_field = field
        .as_any()
        .downcast_ref::<SettingField<T>>()
        .expect("Failed to downcast setting field");
    setting_field.set_value.clone()
}

/// The type of setting field to render.
#[derive(Clone)]
pub enum SettingFieldType {
    Switch,
    Checkbox,
    NumberInput {
        options: NumberFieldOptions,
    },
    Input,
    Dropdown {
        options: Vec<(SharedString, SharedString)>,
        scrollable: bool,
    },
    Element {
        element: Rc<dyn SettingFieldElement<Element = AnyElement>>,
    },
}

impl SettingFieldType {
    #[inline]
    pub(crate) fn is_switch(&self) -> bool {
        matches!(self, SettingFieldType::Switch)
    }

    #[inline]
    pub(crate) fn is_number_input(&self) -> bool {
        matches!(self, SettingFieldType::NumberInput { .. })
    }

    #[inline]
    pub(crate) fn is_input(&self) -> bool {
        matches!(self, SettingFieldType::Input)
    }

    #[inline]
    pub(crate) fn is_dropdown(&self) -> bool {
        matches!(self, SettingFieldType::Dropdown { .. })
    }

    #[inline]
    pub(crate) fn is_element(&self) -> bool {
        matches!(self, SettingFieldType::Element { .. })
    }

    #[inline]
    pub(super) fn dropdown_options(&self) -> Option<&Vec<(SharedString, SharedString)>> {
        match self {
            SettingFieldType::Dropdown { options, .. } => Some(options),
            _ => None,
        }
    }

    #[inline]
    pub(super) fn dropdown_scrollable(&self) -> bool {
        match self {
            SettingFieldType::Dropdown { scrollable, .. } => *scrollable,
            _ => false,
        }
    }

    #[inline]
    pub(super) fn number_input_options(&self) -> Option<&NumberFieldOptions> {
        match self {
            SettingFieldType::NumberInput { options } => Some(options),
            _ => None,
        }
    }

    #[inline]
    pub(super) fn element(&self) -> Rc<dyn SettingFieldElement<Element = AnyElement>> {
        match self {
            SettingFieldType::Element { element } => element.clone(),
            _ => unreachable!("element_render called on non-element field"),
        }
    }
}

/// A setting field that can get and set a value of type T in the App.
pub struct SettingField<T> {
    pub(crate) field_type: SettingFieldType,
    pub(crate) style: StyleRefinement,
    /// Function to get the value for this field.
    pub(crate) value: Rc<dyn Fn(&App) -> T>,
    /// Function to set the value for this field.
    pub(crate) set_value: Rc<dyn Fn(T, &mut App)>,
    pub(crate) default_value: Option<T>,
    /// Optional custom reset behavior, used by `element`/`render` fields whose
    /// state is not expressed through the typed `default_value` mechanism.
    ///
    /// The first closure reports whether the field is "dirty" (controls the
    /// reset button visibility), the second performs the reset.
    pub(crate) reset_handler: Option<ResetHandler>,
}

impl SettingField<bool> {
    /// Create a new Switch field.
    pub fn switch<V, S>(value: V, set_value: S) -> Self
    where
        V: Fn(&App) -> bool + 'static,
        S: Fn(bool, &mut App) + 'static,
    {
        Self::new(SettingFieldType::Switch, value, set_value)
    }

    /// Create a new Checkbox field.
    pub fn checkbox<V, S>(value: V, set_value: S) -> Self
    where
        V: Fn(&App) -> bool + 'static,
        S: Fn(bool, &mut App) + 'static,
    {
        Self::new(SettingFieldType::Checkbox, value, set_value)
    }
}

impl SettingField<SharedString> {
    /// Create a new Input field.
    pub fn input<V, S>(value: V, set_value: S) -> Self
    where
        V: Fn(&App) -> SharedString + 'static,
        S: Fn(SharedString, &mut App) + 'static,
    {
        Self::new(SettingFieldType::Input, value, set_value)
    }

    /// Create a new Dropdown field with the given options.
    ///
    /// The popup menu does not scroll. For long option lists that may exceed
    /// the viewport, use [`Self::scrollable_dropdown`] instead.
    pub fn dropdown<V, S>(
        options: Vec<(SharedString, SharedString)>,
        value: V,
        set_value: S,
    ) -> Self
    where
        V: Fn(&App) -> SharedString + 'static,
        S: Fn(SharedString, &mut App) + 'static,
    {
        Self::new(
            SettingFieldType::Dropdown {
                options,
                scrollable: false,
            },
            value,
            set_value,
        )
    }

    /// Create a new Dropdown field whose popup menu scrolls when its content
    /// exceeds the viewport. Use this for long option lists where the
    /// non-scrolling [`Self::dropdown`] would push items below the fold.
    pub fn scrollable_dropdown<V, S>(
        options: Vec<(SharedString, SharedString)>,
        value: V,
        set_value: S,
    ) -> Self
    where
        V: Fn(&App) -> SharedString + 'static,
        S: Fn(SharedString, &mut App) + 'static,
    {
        Self::new(
            SettingFieldType::Dropdown {
                options,
                scrollable: true,
            },
            value,
            set_value,
        )
    }

    /// Create a new setting field with the given custom element that implements [`SettingFieldElement`] trait.
    ///
    /// See also [`SettingField::render`] for simply building with a render closure.
    pub fn element<E>(element: E) -> Self
    where
        E: SettingFieldElement + 'static,
    {
        Self::new(
            SettingFieldType::Element {
                element: Rc::new(AnySettingFieldElement(element)),
            },
            |_| SharedString::default(),
            |_, _| {},
        )
    }

    /// Create a new setting field with the given element render closure.
    ///
    /// See also [`SettingField::element`] for building with a custom field for more complex scenarios.
    pub fn render<E, R>(element_render: R) -> Self
    where
        E: IntoElement + 'static,
        R: Fn(&RenderOptions, &mut Window, &mut App) -> E + 'static,
    {
        Self::element(
            move |options: &RenderOptions, window: &mut Window, cx: &mut App| {
                (element_render)(options, window, cx).into_any_element()
            },
        )
    }
}

impl SettingField<f64> {
    /// Create a new Number Input field with the given options.
    pub fn number_input<V, S>(options: NumberFieldOptions, value: V, set_value: S) -> Self
    where
        V: Fn(&App) -> f64 + 'static,
        S: Fn(f64, &mut App) + 'static,
    {
        Self::new(SettingFieldType::NumberInput { options }, value, set_value)
    }
}

impl<T> SettingField<T> {
    /// Create a new setting field with the given get and set functions.
    fn new<V, S>(field_type: SettingFieldType, value: V, set_value: S) -> Self
    where
        V: Fn(&App) -> T + 'static,
        S: Fn(T, &mut App) + 'static,
    {
        Self {
            field_type,
            style: StyleRefinement::default(),
            value: Rc::new(value),
            set_value: Rc::new(set_value),
            default_value: None,
            reset_handler: None,
        }
    }

    /// Set the default value for this setting field, default is None.
    ///
    /// If set, this value can be used to reset the setting to its default state.
    /// If not set, the setting cannot be reset.
    pub fn default_value(mut self, default_value: impl Into<T>) -> Self {
        self.default_value = Some(default_value.into());
        self
    }

    /// Provide custom reset behavior for this field.
    ///
    /// This is intended for [`SettingField::element`] / [`SettingField::render`]
    /// fields, whose state is managed externally and therefore not covered by
    /// the typed [`SettingField::default_value`] reset mechanism.
    ///
    /// - `is_dirty` reports whether the field differs from its default and thus
    ///   whether the reset button should appear.
    /// - `reset` performs the reset.
    ///
    /// When set, this takes precedence over the `default_value` based reset.
    pub fn on_reset<D, R>(mut self, is_dirty: D, reset: R) -> Self
    where
        D: Fn(&App) -> bool + 'static,
        R: Fn(&mut Window, &mut App) + 'static,
    {
        self.reset_handler = Some((Rc::new(is_dirty), Rc::new(reset)));
        self
    }
}

impl<T> Styled for SettingField<T> {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }
}

/// A trait for setting fields that allows for dynamic typing.
pub trait AnySettingField {
    fn as_any(&self) -> &dyn std::any::Any;
    fn type_name(&self) -> &'static str;
    fn type_id(&self) -> std::any::TypeId;
    fn field_type(&self) -> &SettingFieldType;
    fn style(&self) -> &StyleRefinement;
    fn is_resettable(&self, cx: &App) -> bool;
    fn reset(&self, window: &mut Window, cx: &mut App);
}

impl<T: Clone + PartialEq + Send + Sync + 'static> AnySettingField for SettingField<T> {
    fn as_any(&self) -> &dyn Any {
        self
    }

    fn type_name(&self) -> &'static str {
        std::any::type_name::<T>()
    }

    fn type_id(&self) -> std::any::TypeId {
        std::any::TypeId::of::<T>()
    }

    fn field_type(&self) -> &SettingFieldType {
        &self.field_type
    }

    fn style(&self) -> &StyleRefinement {
        &self.style
    }

    fn is_resettable(&self, cx: &App) -> bool {
        if let Some((is_dirty, _)) = self.reset_handler.as_ref() {
            return is_dirty(cx);
        }

        // `element`/`render` fields carry no typed value (their `value` always
        // returns the default), so the `default_value` comparison is meaningless
        // for them. Without a custom `on_reset`, they are not resettable.
        if self.field_type.is_element() {
            return false;
        }

        let Some(default_value) = self.default_value.as_ref() else {
            return false;
        };

        &(self.value)(cx) != default_value
    }

    fn reset(&self, window: &mut Window, cx: &mut App) {
        if let Some((_, reset)) = self.reset_handler.as_ref() {
            reset(window, cx);
            return;
        }

        let Some(default_value) = self.default_value.as_ref() else {
            return;
        };

        (self.set_value)(default_value.clone(), cx)
    }
}
