//! Connection brand marks, shared by the library, scripts and chat.
use crate::ui::{self, theme};
use gpui_kit::*;
use serde::Deserialize;
use std::{
    collections::HashMap,
    sync::{Arc, Mutex, OnceLock},
};

#[derive(Deserialize)]
struct Source {
    logos: HashMap<String, Brand>,
}
#[derive(Deserialize)]
struct Brand {
    title: String,
    hex: String,
    #[serde(flatten)]
    artwork: Artwork,
}
#[derive(Deserialize)]
#[serde(rename_all = "lowercase")]
enum Artwork {
    Path(String),
    File(String),
}
#[derive(rust_embed::RustEmbed)]
#[folder = "assets/marks"]
struct Files;

impl Brand {
    fn image(&self, ink: u32) -> Image {
        match &self.artwork {
            Artwork::Path(path) => {
                let svg = format!(
                    r##"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="64" height="64"><path fill="#{ink:06x}" d="{path}"/></svg>"##
                );
                Image::from_bytes(ImageFormat::Svg, svg.into_bytes())
            }
            Artwork::File(file) => {
                let asset = Files::get(file).expect("bundled connection artwork");
                Image::from_bytes(ImageFormat::Png, asset.data.into_owned())
            }
        }
    }
}
struct Catalog {
    brands: HashMap<String, Brand>,
    aliases: HashMap<String, String>,
}
fn normalized(name: &str) -> String {
    name.chars()
        .filter(char::is_ascii_alphanumeric)
        .collect::<String>()
        .to_ascii_lowercase()
}
fn catalog() -> &'static Catalog {
    static CATALOG: OnceLock<Catalog> = OnceLock::new();
    CATALOG.get_or_init(|| {
        let brands = serde_json::from_str::<Source>(include_str!("../assets/logos.json"))
            .expect("bundled connection logo catalog")
            .logos;
        let mut aliases = HashMap::new();
        for (name, brand) in &brands {
            aliases.insert(normalized(name), name.clone());
            aliases.insert(normalized(&brand.title), name.clone());
        }
        Catalog { brands, aliases }
    })
}

/// The same cached artwork is used by Connections, scripts and chat.
/// Single-colour paths follow the theme. Product icons keep their original colours.
pub fn mark(service: &str) -> Option<(Arc<Image>, u32)> {
    type Marks = HashMap<(String, u32), Arc<Image>>;
    static MARKS: OnceLock<Mutex<Marks>> = OnceLock::new();
    let catalog = catalog();
    let name = catalog.aliases.get(&normalized(service))?;
    let brand = catalog.brands.get(name)?;
    let color = u32::from_str_radix(&brand.hex, 16).ok()?;
    let ink = legible(color);
    let mut marks = MARKS.get_or_init(Default::default).lock().ok()?;
    let image = marks
        .entry((name.clone(), ink))
        .or_insert_with(|| Arc::new(brand.image(ink)));
    Some((image.clone(), color))
}

/// A compact brand mark, or an honest neutral letter tile when no mark exists.
pub fn logo(service: &str, size: f32) -> Div {
    let size = if size.is_finite() {
        size.clamp(12., 32.)
    } else {
        16.
    };
    let tile = div().flex_none().size(px(size));
    match mark(service) {
        Some((image, _)) => tile.child(img(image).size_full().flex_none()),
        None => tile
            .rounded(px(size / 4.))
            .bg(rgb(theme::color(ui::INSET)))
            .flex()
            .items_center()
            .justify_center()
            .text_color(rgb(theme::color(ui::SECONDARY)))
            .child(
                gpui_kit::component::Icon::new(gpui_kit::assets::IconName::Plug)
                    .size(px(size * 0.7))
                    .text_color(rgb(theme::color(ui::SECONDARY))),
            ),
    }
}

/// Connections' original legibility policy: pale marks darken on light
/// surfaces; dark marks lift on dark surfaces, with neutral marks using ink.
pub fn legible(color: u32) -> u32 {
    let lum = |c: u32| {
        0.2126 * ((c >> 16) & 0xff) as f32
            + 0.7152 * ((c >> 8) & 0xff) as f32
            + 0.0722 * (c & 0xff) as f32
    };
    let (r, g, b) = ((color >> 16) & 0xff, (color >> 8) & 0xff, color & 0xff);
    let luminance = lum(color);
    if theme::is_dark() {
        if luminance >= 110. {
            return color;
        }
        let spread = r.max(g).max(b) - r.min(g).min(b);
        if spread < 40 {
            return theme::color(ui::INK);
        }
        let t = ((110. - luminance) / 110.).clamp(0.35, 0.65);
        let lift = |c: u32| (c as f32 + (255. - c as f32) * t) as u32;
        return (lift(r) << 16) | (lift(g) << 8) | lift(b);
    }
    if luminance < 150. {
        return color;
    }
    let dim = |c: u32| (c as f32 * 0.5) as u32;
    (dim(r) << 16) | (dim(g) << 8) | dim(b)
}

#[cfg(test)]
mod tests {
    use super::*;
    use core::prelude::v1::test;
    #[test]
    fn aliases_share_the_library_mark_and_missing_marks_have_none() {
        let (calendar, _) = mark("Google Calendar").unwrap();
        assert!(Arc::ptr_eq(&calendar, &mark("google-calendar").unwrap().0));
        for service in ["Unknown service", ""] {
            assert!(mark(service).is_none(), "{service}");
        }
    }
    #[test]
    fn every_bundled_mark_has_artwork_and_both_themes_remain_legible() {
        for brand in catalog().brands.values() {
            match &brand.artwork {
                Artwork::Path(path) => assert!(path.starts_with(['M', 'm']), "{}", brand.title),
                Artwork::File(file) => assert!(Files::get(file).is_some(), "{file}"),
            }
            assert!(
                u32::from_str_radix(&brand.hex, 16).is_ok(),
                "{}",
                brand.title
            );
        }
        assert_eq!(legible(0xffffff), 0x7f7f7f);
        assert_eq!(legible(0x181717), 0x181717);
        let mut dark = theme::DEFAULT;
        dark[0] = 0xeeeeee;
        dark[3] = 0x111111;
        theme::set(dark);
        assert_eq!(legible(0x181717), 0xeeeeee);
        assert_eq!(legible(0xff6600), 0xff6600);
        // Dark, saturated marks such as Sentry's lift rather than vanish.
        let sentry = legible(0x362d59);
        assert!(
            (0..3).all(|i| (sentry >> (i * 8)) & 0xff >= 0x80),
            "{sentry:06x}"
        );
        // Near-black neutral marks such as Notion's take the theme's ink.
        assert_eq!(legible(0x000000), 0xeeeeee);
        theme::set(theme::DEFAULT);
    }
}
