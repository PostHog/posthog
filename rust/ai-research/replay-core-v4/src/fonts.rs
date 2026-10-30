//! Web fonts in a v4 block: the `@font-face` families that the renderer ships, and the font files that the fetcher
//! takes.

use std::collections::HashMap;
use std::sync::LazyLock;

/// The text families the renderer ships. The file documents its own format.
const BUNDLED_FONTS: &str = include_str!("bundled_fonts.txt");

/// A descriptor longer than the longest name the list can hold is not lowercased, because a page controls its length.
const MAX_FAMILY_DESCRIPTOR_LEN: usize = 128;

static BUNDLED_FAMILIES: LazyLock<HashMap<String, String>> = LazyLock::new(|| {
    parse_bundled_fonts(BUNDLED_FONTS)
        .unwrap_or_else(|line| panic!("bundled_fonts.txt has a malformed entry: {line:?}"))
});

fn parse_bundled_fonts(text: &str) -> Result<HashMap<String, String>, String> {
    let mut families = HashMap::new();
    for line in text.lines().map(str::trim) {
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let well_formed = line.len() < MAX_FAMILY_DESCRIPTOR_LEN
            && line.bytes().all(|b| b.is_ascii_alphanumeric() || b == b' ')
            && !line.contains("  ");
        let name = comparable_name(line);
        if !well_formed || families.contains_key(&name) {
            return Err(line.to_owned());
        }
        let slug = name.replace(' ', "-");
        families.insert(name, slug);
    }
    Ok(families)
}

fn comparable_name(name: &str) -> String {
    name.split_ascii_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_ascii_lowercase()
}

/// The family an `@font-face` rule names: one quoted string, or identifiers separated by whitespace. `None` for an
/// escape or a list of families, which the descriptor does not allow.
fn family_name(descriptor: &str) -> Option<&str> {
    let value = descriptor.trim();
    if value.len() > MAX_FAMILY_DESCRIPTOR_LEN || value.contains('\\') {
        return None;
    }
    match value.chars().next()? {
        quote @ ('"' | '\'') => value[1..]
            .strip_suffix(quote)
            .filter(|inner| !inner.contains(quote)),
        _ if value.contains([',', '"', '\'']) => None,
        _ => Some(value),
    }
}

pub fn bundled_font(family_descriptor: &str) -> Option<&'static str> {
    let name = comparable_name(family_name(family_descriptor)?);
    BUNDLED_FAMILIES.get(&name).map(String::as_str)
}

/// Whether the fetcher takes the font file at a URL. Chromium loads neither Embedded OpenType nor SVG fonts, which older
/// stylesheets list next to WOFF, so a fetch of one would only spend the origin's politeness budget.
pub fn is_fetched_font_url(url: &str) -> bool {
    let path = url.split(['?', '#']).next().unwrap_or_default();
    let file = path.rsplit(['/', '\\']).next().unwrap_or_default();
    let extension = file.rsplit_once('.').map_or("", |(_, extension)| extension);
    !["eot", "svg", "svgz"]
        .iter()
        .any(|refused| extension.eq_ignore_ascii_case(refused))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_shipped_list_parses() {
        assert!(BUNDLED_FAMILIES.len() > 50);
    }

    #[test]
    fn a_malformed_or_repeated_entry_fails() {
        for list in ["Inter\ninter", "Open  Sans", "Inter;", "\"Inter\""] {
            assert!(parse_bundled_fonts(list).is_err(), "{list:?}");
        }
    }

    #[test]
    fn names_a_bundled_family_however_the_rule_writes_it() {
        for descriptor in [
            "Open Sans",
            "  'Open Sans' ",
            "\"open   sans\"",
            "OPEN\tSANS",
        ] {
            assert_eq!(
                bundled_font(descriptor),
                Some("open-sans"),
                "{descriptor:?}"
            );
        }
        for descriptor in [
            "Open Sans, sans-serif",
            "\"Open Sans",
            "Open\\ Sans",
            "Brand Sans",
            "Font Awesome 6 Free",
            "",
        ] {
            assert_eq!(bundled_font(descriptor), None, "{descriptor:?}");
        }
    }

    #[test]
    fn skips_formats_a_renderer_never_loads() {
        for url in [
            "https://cdn.example.com/fa.eot?#iefix",
            "https://cdn.example.com/fa.svg#fontawesome",
            "https://cdn.example.com/FA.EOT",
        ] {
            assert!(!is_fetched_font_url(url), "{url}");
        }
        for url in [
            "https://cdn.example.com/fa.woff2?v=4.7.0",
            "https://cdn.example.com/font",
            "https://cdn.example.com/eot/font.woff",
        ] {
            assert!(is_fetched_font_url(url), "{url}");
        }
    }
}
