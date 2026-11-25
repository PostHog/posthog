//! Keeps the theme's default monospace family on a font the machine has.
//!
//! GPUI panics on the first line it lays out in a family it cannot find, and
//! `Font::fallbacks` does not help there: it is a cascade list for missing
//! glyphs, consulted only after the family itself has loaded. The theme's
//! platform default is a bare name, so a machine without that font would crash
//! on its first code block. This probe swaps the default for an installed
//! alternative before any text is laid out.
//!
//! Only the platform default is probed. A family the application or a theme
//! file chose explicitly is used as-is: it is usually embedded through
//! `add_fonts`, and Windows lists families under their localized names, so an
//! English name for a CJK font would look missing when it is not.

use gpui::{App, SharedString};
use gpui_base::TypographyTokens;
use std::sync::OnceLock;

/// Monospace families tried, in order, when the platform default is missing.
const MONO_FONT_ALTERNATES: &[&str] = if cfg!(target_os = "macos") {
    &["Monaco", "Courier New"]
} else if cfg!(target_os = "windows") {
    &["Cascadia Mono", "Courier New"]
} else {
    &["Noto Sans Mono", "Liberation Mono", "Ubuntu Mono"]
};

/// The virtual family GPUI resolves on every platform; the last resort when
/// neither the default nor an alternate is installed.
const SYSTEM_UI_FONT: &str = ".SystemUIFont";

/// The monospace family the theme picks when none is configured.
pub(super) fn default_mono_font_family() -> SharedString {
    TypographyTokens::default().mono
}

/// Replaces the platform-default monospace family on the global theme with one
/// that is installed. A family chosen explicitly is left alone.
pub(super) fn resolve_default_mono_font(cx: &mut App) {
    if cx.global::<super::Theme>().mono_font_family != default_mono_font_family() {
        return;
    }
    let family = installed_default_mono_font_family(cx);
    cx.global_mut::<super::Theme>().mono_font_family = family;
}

/// The installed stand-in for the platform default, resolved once per process.
fn installed_default_mono_font_family(cx: &App) -> SharedString {
    static RESOLVED: OnceLock<SharedString> = OnceLock::new();
    RESOLVED
        .get_or_init(|| {
            let default = default_mono_font_family();
            let family = first_installed(&default, MONO_FONT_ALTERNATES, installed_font_names(cx));
            if family != default {
                tracing::warn!(
                    "Monospace font {default:?} is not installed, using {family:?} instead."
                );
            }
            family
        })
        .clone()
}

/// The families installed on the machine, listed once per process.
///
/// Enumerating fonts costs around a hundred milliseconds on macOS, and the
/// answer only depends on the system fonts, which do not change while the
/// process runs.
pub(super) fn installed_font_names(cx: &App) -> &'static [String] {
    static NAMES: OnceLock<Vec<String>> = OnceLock::new();
    NAMES.get_or_init(|| cx.text_system().all_font_names())
}

/// `default` when it is installed, else the first installed alternate, else
/// `.SystemUIFont`.
fn first_installed(default: &str, alternates: &[&str], installed: &[String]) -> SharedString {
    std::iter::once(default)
        .chain(alternates.iter().copied())
        .find(|candidate| installed.iter().any(|name| name == candidate))
        .unwrap_or(SYSTEM_UI_FONT)
        .to_string()
        .into()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn names(names: &[&str]) -> Vec<String> {
        names.iter().map(|name| name.to_string()).collect()
    }

    #[test]
    fn keeps_the_default_when_it_is_installed() {
        let installed = names(&["Monaco", "Menlo", ".SystemUIFont"]);
        assert_eq!(
            first_installed("Menlo", &["Monaco"], &installed),
            SharedString::from("Menlo")
        );
    }

    #[test]
    fn falls_through_the_alternates_in_order() {
        let installed = names(&["Courier New", "Monaco", ".SystemUIFont"]);
        assert_eq!(
            first_installed("Menlo", &["Monaco", "Courier New"], &installed),
            SharedString::from("Monaco")
        );
    }

    #[test]
    fn falls_back_to_the_system_font_when_nothing_is_installed() {
        let installed = names(&["Helvetica", ".SystemUIFont"]);
        assert_eq!(
            first_installed("Menlo", &["Monaco"], &installed),
            SharedString::from(".SystemUIFont")
        );
    }
}
