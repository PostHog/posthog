use std::{rc::Rc, sync::Arc};

use crate::{ActiveTheme, Sizable, Size};
use gpui::{
    AnyElement, App, AppContext, Context, Entity, Global, Hsla, IntoElement, Pixels, Radians,
    Render, RenderOnce, SharedString, StyleRefinement, Styled, Svg, Transformation, Window,
    prelude::FluentBuilder as _, svg,
};
pub use gpui_kit_assets::IconNamed;

// Preserve the original enum (including exhaustive matches and inherent view)
// while the complete, shared catalog is owned by gpui-kit-assets.
macro_rules! component_icon_names {
    ($($name:ident => $path:literal,)*) => {
        /// Default component icon names, retained for source compatibility.
        /// For the complete Lucide catalog, use `gpui_kit_assets::IconName`.
        #[derive(Clone, IntoElement)]
        pub enum IconName {
            $($name,)*
        }

        impl From<IconName> for gpui_kit_assets::IconName {
            fn from(name: IconName) -> Self {
                match name {
                    $(IconName::$name => Self::$name,)*
                }
            }
        }

        impl IconNamed for IconName {
            fn path(self) -> SharedString {
                match self { $(Self::$name => $path,)* }.into()
            }
        }
    };
}

gpui_kit_assets::__component_icon_names!(component_icon_names);

impl IconName {
    /// Return the icon as an Entity<Icon>.
    pub fn view(self, cx: &mut App) -> Entity<Icon> {
        Icon::build(self).view(cx)
    }
}

impl From<IconName> for AnyElement {
    fn from(name: IconName) -> Self {
        Icon::build(name).into_any_element()
    }
}

impl RenderOnce for IconName {
    fn render(self, _: &mut Window, _: &mut App) -> impl IntoElement {
        Icon::build(self)
    }
}

impl<T: IconNamed> From<T> for Icon {
    fn from(value: T) -> Self {
        Icon::build(value)
    }
}

/// Component view construction for the shared `gpui_kit_assets::IconName`.
/// The legacy component `IconName` retains its inherent `view` method.
pub trait IconNameExt {
    fn view(self, cx: &mut App) -> Entity<Icon>;
}

impl IconNameExt for gpui_kit_assets::IconName {
    fn view(self, cx: &mut App) -> Entity<Icon> {
        Icon::build(self).view(cx)
    }
}

struct IconResolver(Rc<dyn Fn(&str, &App) -> Option<SharedString>>);

impl Global for IconResolver {}

/// Set the hook every [`Icon`] drawn from an asset path asks for the path to draw,
/// including the icons components draw inside their own controls.
///
/// The resolver receives the icon's path (for example `icons/check.svg`) and returns
/// the path to draw in its place, or `None` to keep it. GPUI caches a rendered SVG by
/// its path, so returning a new path is how an application switches icon styles at
/// runtime; the application's [`gpui::AssetSource`] must load the returned path.
/// Icons created with [`Icon::data`] are not resolved.
///
/// The resolver runs every time an icon is drawn and should be cheap. Call
/// [`App::refresh_windows`] after changing what it returns.
pub fn set_icon_resolver(
    cx: &mut App,
    resolver: impl Fn(&str, &App) -> Option<SharedString> + 'static,
) {
    cx.set_global(IconResolver(Rc::new(resolver)));
}

/// Return the path to draw for the icon at `path`: the answer of the resolver set with
/// [`set_icon_resolver`], or `path` itself.
pub fn resolve_icon_path(path: SharedString, cx: &App) -> SharedString {
    match cx.try_global::<IconResolver>() {
        Some(resolver) if !path.is_empty() => (resolver.0)(&path, cx).unwrap_or(path),
        _ => path,
    }
}

#[derive(Clone)]
pub(crate) enum IconSource {
    Path(SharedString),
    Data(Arc<[u8]>),
}

#[derive(Clone, IntoElement)]
pub struct Icon {
    style: StyleRefinement,
    source: IconSource,
    text_color: Option<Hsla>,
    size: Option<Size>,
    transformation: Option<Transformation>,
}

impl Default for Icon {
    fn default() -> Self {
        Self {
            style: StyleRefinement::default(),
            source: IconSource::Path("".into()),
            text_color: None,
            size: None,
            transformation: None,
        }
    }
}

impl Icon {
    pub fn new(icon: impl Into<Icon>) -> Self {
        icon.into()
    }

    fn build(name: impl IconNamed) -> Self {
        Self::default().path(name.path())
    }

    /// Set the icon path of the Assets bundle
    ///
    /// For example: `icons/foo.svg`
    /// Replaces any previously set path or SVG data.
    pub fn path(mut self, path: impl Into<SharedString>) -> Self {
        self.source = IconSource::Path(path.into());
        self
    }

    /// Set raw SVG bytes without registering an asset path.
    ///
    /// Copies the bytes into shared storage; the input need not be static.
    /// Cloning the icon shares those bytes. Replaces any previously set path or data.
    /// Parsing and rendering follow GPUI's SVG behavior.
    ///
    /// ```
    /// use gpui_component::Icon;
    ///
    /// let bytes = br#"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
    ///     <path d="M4 12h16" stroke="currentColor"/>
    /// </svg>"#;
    /// let icon = Icon::default().data(bytes);
    /// ```
    pub fn data(mut self, data: &[u8]) -> Self {
        self.source = IconSource::Data(Arc::from(data));
        self
    }

    #[cfg(any(target_os = "macos", target_os = "windows", test))]
    pub(crate) fn source_ref(&self) -> &IconSource {
        &self.source
    }

    /// Whether `other` takes up exactly the same space as this icon. The
    /// source, color and transformation change only what it paints.
    pub(crate) fn same_layout(&self, other: &Self) -> bool {
        self.style == other.style && self.size == other.size
    }

    /// Create a new view for the icon
    pub fn view(self, cx: &mut App) -> Entity<Icon> {
        cx.new(|_| self)
    }

    /// Set the SVG transformation, replacing any previous transformation or rotation.
    pub fn transform(mut self, transformation: gpui::Transformation) -> Self {
        self.transformation = Some(transformation);
        self
    }

    pub fn empty() -> Self {
        Self::default()
    }

    /// Rotate the icon by the given angle
    ///
    /// Replaces any previous transformation or rotation.
    pub fn rotate(mut self, radians: impl Into<Radians>) -> Self {
        self.transformation = Some(Transformation::rotate(radians));
        self
    }

    fn resolved(mut self, cx: &App) -> Self {
        if let IconSource::Path(path) = self.source {
            self.source = IconSource::Path(resolve_icon_path(path, cx));
        }
        self
    }

    fn into_svg(self, text_size: Pixels, fallback_color: Hsla) -> Svg {
        let text_color = self.text_color.unwrap_or(fallback_color);
        let has_base_size = self.style.size.width.is_some() || self.style.size.height.is_some();

        svg()
            .map(|mut this| {
                *this.style() = self.style;
                this
            })
            .flex_shrink_0()
            .text_color(text_color)
            .when(!has_base_size, |this| this.size(text_size))
            .when_some(self.size, |this, size| match size {
                Size::Size(px) => this.size(px),
                Size::XSmall => this.size_3(),
                Size::Small => this.size_3p5(),
                Size::Medium => this.size_4(),
                Size::Large => this.size_6(),
            })
            .map(|this| match self.source {
                IconSource::Path(path) => this.path(path),
                IconSource::Data(data) => this.data(&data),
            })
            .when_some(self.transformation, |this, transformation| {
                this.with_transformation(transformation)
            })
    }
}

impl Styled for Icon {
    fn style(&mut self) -> &mut StyleRefinement {
        &mut self.style
    }

    fn text_color(mut self, color: impl Into<Hsla>) -> Self {
        self.text_color = Some(color.into());
        self
    }
}

impl Sizable for Icon {
    fn with_size(mut self, size: impl Into<Size>) -> Self {
        self.size = Some(size.into());
        self
    }
}

impl RenderOnce for Icon {
    fn render(self, window: &mut Window, cx: &mut App) -> impl IntoElement {
        let text_size = window.text_style().font_size.to_pixels(window.rem_size());
        self.resolved(cx)
            .into_svg(text_size, window.text_style().color)
    }
}

impl From<Icon> for AnyElement {
    fn from(val: Icon) -> Self {
        val.into_any_element()
    }
}

impl Render for Icon {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let text_size = window.text_style().font_size.to_pixels(window.rem_size());
        self.clone()
            .resolved(cx)
            .into_svg(text_size, cx.theme().foreground)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use gpui::{px, size};

    const SVG: &[u8] = include_bytes!("../../assets/assets/icons/arrow-up.svg");

    #[test]
    fn test_icon_builder_preserves_owned_data_and_transform_on_clone() {
        let transformation = Transformation::scale(size(0.5, 0.5))
            .with_rotation(gpui::radians(std::f32::consts::FRAC_PI_2));
        let icon = {
            let bytes = SVG.to_vec();
            Icon::default()
                .data(&bytes)
                .large()
                .text_color(gpui::red())
                .transform(transformation)
        };
        let cloned = icon.clone();
        let (IconSource::Data(original), IconSource::Data(copy)) = (&icon.source, &cloned.source)
        else {
            panic!("cloning must preserve the data source");
        };
        assert_eq!(copy.as_ref(), SVG);
        assert!(Arc::ptr_eq(original, copy));
        assert_eq!(cloned.transformation, Some(transformation));
        assert_eq!(cloned.size, icon.size);
        assert_eq!(cloned.text_color, icon.text_color);

        let mut svg = cloned.into_svg(px(12.), gpui::blue());
        assert_eq!(svg.style().text.color, Some(gpui::red()));
        assert_eq!(svg.style().size.width, Some(gpui::rems(1.5).into()));

        let rotated = icon.rotate(gpui::radians(std::f32::consts::PI)).clone();
        assert_eq!(
            rotated.transformation,
            Some(Transformation::rotate(gpui::radians(std::f32::consts::PI)))
        );
    }

    #[test]
    fn test_icon_source_builders_replace_previous_source() {
        let icon = Icon::new(IconName::Search).data(SVG);
        assert!(matches!(icon.source_ref(), IconSource::Data(bytes) if bytes.as_ref() == SVG));

        let icon = icon.path("icons/replacement.svg");
        assert!(
            matches!(icon.source_ref(), IconSource::Path(path) if path == "icons/replacement.svg")
        );

        let icon = icon.data(SVG).data(b"replacement");
        assert!(
            matches!(icon.source_ref(), IconSource::Data(bytes) if bytes.as_ref() == b"replacement")
        );

        let icon = icon.path("");
        assert!(matches!(icon.source_ref(), IconSource::Path(path) if path.is_empty()));
    }

    #[gpui::test]
    fn test_icon_resolver_replaces_the_path_to_draw(cx: &mut gpui::TestAppContext) {
        fn drawn_path(icon: Icon, cx: &App) -> SharedString {
            match icon.resolved(cx).source {
                IconSource::Path(path) => path,
                IconSource::Data(_) => panic!("resolving must keep the source type"),
            }
        }

        cx.update(|cx| {
            let search = IconName::Search.path();
            assert_eq!(drawn_path(Icon::new(IconName::Search), cx), search);

            let asked = Rc::new(std::cell::RefCell::new(Vec::<String>::new()));
            set_icon_resolver(cx, {
                let asked = asked.clone();
                let search = search.clone();
                move |path, _| {
                    asked.borrow_mut().push(path.to_string());
                    (path == search.as_ref()).then(|| "icons/alt/search.svg".into())
                }
            });

            assert_eq!(
                drawn_path(Icon::new(IconName::Search), cx),
                "icons/alt/search.svg"
            );
            assert_eq!(
                drawn_path(Icon::new(IconName::Check), cx),
                IconName::Check.path()
            );
            assert_eq!(drawn_path(Icon::empty(), cx), "");
            assert!(matches!(
                Icon::default().data(SVG).resolved(cx).source,
                IconSource::Data(_)
            ));
            assert_eq!(
                *asked.borrow(),
                [search.to_string(), IconName::Check.path().to_string()]
            );
        });
    }
}
