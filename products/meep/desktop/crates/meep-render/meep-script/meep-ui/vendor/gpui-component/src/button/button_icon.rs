use crate::{Icon, Sizable, Size, progress::ProgressCircle, spinner::Spinner};
use gpui::{App, IntoElement, RenderOnce, Window, prelude::FluentBuilder};

/// Button icon which can be an Icon, Spinner, or Progress use for `icon` method of Button.
#[doc(hidden)]
#[derive(IntoElement)]
pub struct ButtonIcon {
    icon: ButtonIconVariant,
    loading_icon: Option<Icon>,
    loading: bool,
    size: Size,
}

impl<T> From<T> for ButtonIcon
where
    T: Into<ButtonIconVariant>,
{
    fn from(icon: T) -> Self {
        ButtonIcon::new(icon)
    }
}

impl ButtonIcon {
    /// Creates a new ButtonIcon with the given icon.
    pub fn new(icon: impl Into<ButtonIconVariant>) -> Self {
        Self {
            icon: icon.into(),
            loading_icon: None,
            loading: false,
            size: Size::Medium,
        }
    }

    pub(crate) fn loading_icon(mut self, icon: Option<Icon>) -> Self {
        self.loading_icon = icon;
        self
    }

    pub(crate) fn loading(mut self, loading: bool) -> Self {
        self.loading = loading;
        self
    }
}

impl Sizable for ButtonIcon {
    fn with_size(mut self, size: impl Into<crate::Size>) -> Self {
        self.size = size.into();
        self
    }
}

/// Button icon which can be an Icon, Spinner, Progress, or ProgressCircle use for `icon` method of Button.
#[doc(hidden)]
#[derive(IntoElement)]
pub enum ButtonIconVariant {
    Icon(Icon),
    Spinner(Spinner),
    Progress(ProgressCircle),
}

impl<T> From<T> for ButtonIconVariant
where
    T: Into<Icon>,
{
    fn from(icon: T) -> Self {
        Self::Icon(icon.into())
    }
}

impl From<Spinner> for ButtonIconVariant {
    fn from(spinner: Spinner) -> Self {
        Self::Spinner(spinner)
    }
}

impl From<ProgressCircle> for ButtonIconVariant {
    fn from(progress: ProgressCircle) -> Self {
        Self::Progress(progress)
    }
}

impl ButtonIconVariant {
    /// Returns true if the ButtonIconKind is an Icon.
    #[inline]
    pub(crate) fn is_spinner(&self) -> bool {
        matches!(self, Self::Spinner(_))
    }

    /// Returns true if the ButtonIconKind is a Progress or ProgressCircle.
    #[inline]
    pub(crate) fn is_progress(&self) -> bool {
        matches!(self, Self::Progress(_))
    }
}

impl Sizable for ButtonIconVariant {
    fn with_size(self, size: impl Into<crate::Size>) -> Self {
        match self {
            Self::Icon(icon) => Self::Icon(icon.with_size(size)),
            Self::Spinner(spinner) => Self::Spinner(spinner.with_size(size)),
            Self::Progress(progress) => Self::Progress(progress.with_size(size)),
        }
    }
}

impl RenderOnce for ButtonIconVariant {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        match self {
            Self::Icon(icon) => icon.into_any_element(),
            Self::Spinner(spinner) => spinner.into_any_element(),
            Self::Progress(progress) => progress.into_any_element(),
        }
    }
}

impl RenderOnce for ButtonIcon {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        if self.loading {
            if self.icon.is_spinner() || self.icon.is_progress() {
                self.icon.with_size(self.size).into_any_element()
            } else {
                Spinner::new()
                    .when_some(self.loading_icon, |this, icon| this.icon(icon))
                    .with_size(self.size)
                    .into_any_element()
            }
        } else {
            self.icon.with_size(self.size).into_any_element()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::IconName;

    #[gpui::test]
    fn test_button_icon_builder(_cx: &mut gpui::TestAppContext) {
        let custom_icon = Icon::new(IconName::Loader);
        let icon = ButtonIcon::new(IconName::Plus)
            .loading(true)
            .loading_icon(Some(custom_icon))
            .large();

        assert!(icon.loading);
        assert!(icon.loading_icon.is_some());
        assert_eq!(icon.size, Size::Large);
    }

    #[gpui::test]
    fn test_button_icon_variant_types(_cx: &mut gpui::TestAppContext) {
        // Test Icon variant
        let icon_variant = ButtonIconVariant::Icon(Icon::new(IconName::Plus));
        assert!(!icon_variant.is_spinner());
        assert!(!icon_variant.is_progress());

        // Test Spinner variant
        let spinner_variant = ButtonIconVariant::Spinner(Spinner::new());
        assert!(spinner_variant.is_spinner());
        assert!(!spinner_variant.is_progress());

        // Test Progress variant
        let progress_variant = ButtonIconVariant::Progress(ProgressCircle::new(75));
        assert!(!progress_variant.is_spinner());
        assert!(progress_variant.is_progress());
    }

    #[test]
    fn test_custom_data_icon_converts_through_component_slots() {
        use crate::{icon::IconSource, menu::PopupMenuItem};

        struct Search;
        impl From<Search> for Icon {
            fn from(_: Search) -> Self {
                Icon::default().data(include_bytes!("../../../assets/assets/icons/search.svg"))
            }
        }

        let button = ButtonIcon::from(Search)
            .loading(true)
            .loading_icon(Some(Search.into()));
        let ButtonIconVariant::Icon(icon) = button.icon else {
            panic!("custom data icons must use the standard icon variant");
        };
        assert!(matches!(icon.source_ref(), IconSource::Data(_)));
        assert!(button.loading);
        assert!(matches!(
            button.loading_icon.unwrap().source_ref(),
            IconSource::Data(_)
        ));

        let menu = PopupMenuItem::new("Search").icon(Search);
        let PopupMenuItem::Item {
            icon: Some(icon), ..
        } = menu
        else {
            panic!("custom data icons must be accepted by menu slots");
        };
        assert!(matches!(icon.source_ref(), IconSource::Data(_)));
    }
}
