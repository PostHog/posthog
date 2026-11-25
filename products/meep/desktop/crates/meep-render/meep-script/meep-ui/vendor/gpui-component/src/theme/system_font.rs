//! Keeps the theme's UI family on the font GPUI actually draws it with.
//!
//! The default UI family is the virtual `.SystemUIFont`, which GPUI maps to a
//! platform name and, when that name is not installed, resolves through its
//! own fallback stack. The fallback works, but it is paid for on every text
//! run of every frame: the failed lookup is cached as an error that is
//! formatted and allocated again each time it is hit, once per entry of the
//! stack that is missing too. On Linux the mapped name is one most desktops
//! do not ship, so this is the common case there.
//!
//! This probe asks GPUI once which family `.SystemUIFont` lands on and, when
//! that is an installed family rather than the system font itself, names it
//! on the theme directly, so every later lookup hits the cache and the text
//! is drawn exactly as before. A family the application or a theme file
//! chose explicitly is used as-is.
//!
//! GPUI panics when neither `.SystemUIFont` nor any family of its fallback
//! stack is installed. On the web the text system starts with no fonts at
//! all and only sees the ones the application adds, usually after `init`, so
//! the probe does nothing while no font is installed: there would be nothing
//! to name anyway.

use gpui::{App, SharedString, font};

use super::mono_font::installed_font_names;

/// The virtual family GPUI resolves on every platform.
const SYSTEM_UI_FONT: &str = ".SystemUIFont";

/// Replaces `.SystemUIFont` on the global theme with the installed family GPUI
/// resolves it to, when that differs. Any other family is left alone.
pub(super) fn resolve_default_font(cx: &mut App) {
    if cx.global::<super::Theme>().font_family != SYSTEM_UI_FONT {
        return;
    }
    let installed = installed_font_names(cx);
    if installed.is_empty() {
        return;
    }
    let text_system = cx.text_system();
    let resolved = text_system
        .get_font_for_id(text_system.resolve_font(&font(SYSTEM_UI_FONT)))
        .map(|font| font.family);
    let Some(family) = substitute(SYSTEM_UI_FONT, resolved.as_deref(), installed) else {
        return;
    };
    tracing::info!("UI font {SYSTEM_UI_FONT:?} resolves to {family:?}, naming it on the theme.");
    cx.global_mut::<super::Theme>().font_family = family;
}

/// The family to name instead of `requested`: the one GPUI resolved it to,
/// when that is a different, installed family.
fn substitute(
    requested: &str,
    resolved: Option<&str>,
    installed: &[String],
) -> Option<SharedString> {
    let resolved = resolved.filter(|resolved| *resolved != requested)?;
    installed
        .iter()
        .any(|name| name == resolved)
        .then(|| resolved.to_string().into())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn names(names: &[&str]) -> Vec<String> {
        names.iter().map(|name| name.to_string()).collect()
    }

    #[test]
    fn keeps_the_system_font_when_it_resolves_to_itself() {
        let installed = names(&["Noto Sans", ".SystemUIFont"]);
        assert_eq!(
            substitute(".SystemUIFont", Some(".SystemUIFont"), &installed),
            None
        );
    }

    #[test]
    fn names_the_installed_family_the_system_font_fell_back_to() {
        let installed = names(&["Noto Sans", "DejaVu Sans"]);
        assert_eq!(
            substitute(".SystemUIFont", Some("Noto Sans"), &installed),
            Some(SharedString::from("Noto Sans"))
        );
    }

    #[test]
    fn keeps_the_system_font_when_the_resolved_family_is_not_installed() {
        let installed = Vec::new();
        assert_eq!(
            substitute(".SystemUIFont", Some("Noto Sans"), &installed),
            None
        );
        assert_eq!(substitute(".SystemUIFont", None, &installed), None);
    }
}
