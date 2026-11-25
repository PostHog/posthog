use std::{collections::HashMap, fmt::Display};

use gpui::{
    Background, Hsla, LinearColorStop, SharedString, hsla, linear_color_stop, linear_gradient,
};
use serde::{Deserialize, Deserializer, de::Error as _};

use anyhow::{Error, Result, anyhow};

/// Create a [`gpui::Hsla`] color.
///
/// - h: 0..360.0
/// - s: 0.0..100.0
/// - l: 0.0..100.0
#[inline]
pub fn hsl(h: f32, s: f32, l: f32) -> Hsla {
    hsla(h / 360., s / 100.0, l / 100.0, 1.0)
}

pub trait Colorize: Sized {
    /// Returns a new color with the given opacity.
    ///
    /// The opacity is a value between 0.0 and 1.0, where 0.0 is fully transparent and 1.0 is fully opaque.
    fn opacity(&self, opacity: f32) -> Self;
    /// Returns a new color with each channel divided by the given divisor.
    ///
    /// The divisor in range of 0.0 .. 1.0
    fn divide(&self, divisor: f32) -> Self;
    /// Return inverted color
    fn invert(&self) -> Self;
    /// Return inverted lightness
    fn invert_l(&self) -> Self;
    /// Return a new color with the lightness increased by the given factor.
    ///
    /// factor range: 0.0 .. 1.0
    fn lighten(&self, amount: f32) -> Self;
    /// Return a new color with the darkness increased by the given factor.
    ///
    /// factor range: 0.0 .. 1.0
    fn darken(&self, amount: f32) -> Self;
    /// Return a new color with the same lightness and alpha but different hue and saturation.
    fn apply(&self, base_color: Self) -> Self;

    /// Mix two colors together, the `factor` is a value between 0.0 and 1.0 for first color.
    fn mix(&self, other: Self, factor: f32) -> Self;
    /// Mix two colors together in Oklab color space, the `factor` is a value between 0.0 and 1.0 for first color.
    ///
    /// This is similar to CSS `color-mix(in oklab, color1 factor%, color2)`.
    fn mix_oklab(&self, other: Self, factor: f32) -> Self;
    /// Change the `Hue` of the color by the given in range: 0.0 .. 1.0
    fn hue(&self, hue: f32) -> Self;
    /// Change the `Saturation` of the color by the given value in range: 0.0 .. 1.0
    fn saturation(&self, saturation: f32) -> Self;
    /// Change the `Lightness` of the color by the given value in range: 0.0 .. 1.0
    fn lightness(&self, lightness: f32) -> Self;

    /// Convert the color to a hex string. For example, "#F8FAFC".
    fn to_hex(&self) -> String;
    /// Parse a hex string to a color.
    fn parse_hex(hex: &str) -> Result<Self>;
}

/// Helper functions for Oklab color space conversions
mod oklab {
    use gpui::Rgba;

    /// Convert sRGB component to linear RGB
    #[inline]
    fn to_linear(c: f32) -> f32 {
        if c <= 0.04045 {
            c / 12.92
        } else {
            ((c + 0.055) / 1.055).powf(2.4)
        }
    }

    /// Convert linear RGB component to sRGB
    #[inline]
    fn from_linear(c: f32) -> f32 {
        if c <= 0.0031308 {
            c * 12.92
        } else {
            1.055 * c.powf(1.0 / 2.4) - 0.055
        }
    }

    /// Convert RGB to Oklab color space
    #[allow(non_snake_case)]
    pub fn rgb_to_oklab(rgb: Rgba) -> (f32, f32, f32) {
        // sRGB to linear RGB
        let lr = to_linear(rgb.r);
        let lg = to_linear(rgb.g);
        let lb = to_linear(rgb.b);

        // Linear RGB to LMS
        let l = 0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb;
        let m = 0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb;
        let s = 0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb;

        // LMS to Oklab (using cube root)
        let l_ = l.cbrt();
        let m_ = m.cbrt();
        let s_ = s.cbrt();

        let L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_;
        let a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_;
        let b = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_;

        (L, a, b)
    }

    /// Convert Oklab to RGB color space
    #[allow(non_snake_case)]
    pub fn oklab_to_rgb(L: f32, a: f32, b: f32) -> Rgba {
        // Oklab to LMS
        let l_ = L + 0.3963377774 * a + 0.2158037573 * b;
        let m_ = L - 0.1055613458 * a - 0.0638541728 * b;
        let s_ = L - 0.0894841775 * a - 1.2914855480 * b;

        let l = l_ * l_ * l_;
        let m = m_ * m_ * m_;
        let s = s_ * s_ * s_;

        // LMS to Linear RGB
        let lr = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
        let lg = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
        let lb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s;

        // Linear RGB to sRGB
        Rgba {
            r: from_linear(lr).clamp(0.0, 1.0),
            g: from_linear(lg).clamp(0.0, 1.0),
            b: from_linear(lb).clamp(0.0, 1.0),
            a: 1.0,
        }
    }
}

/// Builds a color from OkLCH, the cylindrical form of the perceptually uniform
/// Oklab color space.
///
/// Unlike HSL, rotating `hue` while holding `lightness` and `chroma` keeps the
/// perceived brightness and vividness of every hue equal, so a generated color
/// ring reads as one family instead of a raw rainbow.
///
/// `lightness` is `0.0 .. 1.0`, `chroma` is an absolute Oklab distance
/// (roughly `0.0 .. 0.37`), and `hue` is in degrees. A request outside the sRGB
/// gamut is clipped per channel, which costs a little chroma but not the hue.
pub fn oklch(lightness: f32, chroma: f32, hue: f32) -> Hsla {
    let hue = hue.to_radians();
    let rgb = oklab::oklab_to_rgb(lightness, chroma * hue.cos(), chroma * hue.sin());
    rgb.into()
}

impl Colorize for Hsla {
    fn opacity(&self, factor: f32) -> Self {
        Self {
            a: self.a * factor.clamp(0.0, 1.0),
            ..*self
        }
    }

    fn divide(&self, divisor: f32) -> Self {
        Self {
            a: divisor,
            ..*self
        }
    }

    fn invert(&self) -> Self {
        Self {
            h: 1.0 - self.h,
            s: 1.0 - self.s,
            l: 1.0 - self.l,
            a: self.a,
        }
    }

    fn invert_l(&self) -> Self {
        Self {
            l: 1.0 - self.l,
            ..*self
        }
    }

    fn lighten(&self, factor: f32) -> Self {
        let l = self.l * (1.0 + factor.clamp(0.0, 1.0));

        Hsla { l, ..*self }
    }

    fn darken(&self, factor: f32) -> Self {
        let l = self.l * (1.0 - factor.clamp(0.0, 1.0));

        Self { l, ..*self }
    }

    fn apply(&self, new_color: Self) -> Self {
        Hsla {
            h: new_color.h,
            s: new_color.s,
            l: self.l,
            a: self.a,
        }
    }

    /// Reference:
    /// https://github.com/bevyengine/bevy/blob/85eceb022da0326b47ac2b0d9202c9c9f01835bb/crates/bevy_color/src/hsla.rs#L112
    fn mix(&self, other: Self, factor: f32) -> Self {
        let factor = factor.clamp(0.0, 1.0);
        let inv = 1.0 - factor;

        #[inline]
        fn lerp_hue(a: f32, b: f32, t: f32) -> f32 {
            let diff = (b - a + 180.0).rem_euclid(360.) - 180.;
            (a + diff * t).rem_euclid(360.0)
        }

        Hsla {
            h: lerp_hue(self.h * 360., other.h * 360., factor) / 360.,
            s: self.s * factor + other.s * inv,
            l: self.l * factor + other.l * inv,
            a: self.a * factor + other.a * inv,
        }
    }

    #[allow(non_snake_case)]
    fn mix_oklab(&self, other: Self, factor: f32) -> Self {
        let factor = factor.clamp(0.0, 1.0);
        let inv = 1.0 - factor;

        // Interpolate alpha first
        let result_alpha = self.a * factor + other.a * inv;

        // Handle the case where result alpha is zero
        if result_alpha == 0.0 {
            return Self {
                h: 0.0,
                s: 0.0,
                l: 0.0,
                a: 0.0,
            };
        }

        // Convert both colors to RGB
        let rgb1 = self.to_rgb();
        let rgb2 = other.to_rgb();

        // Convert to Oklab color space
        let (l1, a1, b1) = oklab::rgb_to_oklab(rgb1);
        let (l2, a2, b2) = oklab::rgb_to_oklab(rgb2);

        // Premultiply alpha in Oklab space (using alpha-premultiplied interpolation)
        // This matches CSS color-mix behavior
        let alpha1 = self.a;
        let alpha2 = other.a;

        // Premultiply
        let l1_pm = l1 * alpha1;
        let a1_pm = a1 * alpha1;
        let b1_pm = b1 * alpha1;

        let l2_pm = l2 * alpha2;
        let a2_pm = a2 * alpha2;
        let b2_pm = b2 * alpha2;

        // Interpolate premultiplied values
        let L_pm = l1_pm * factor + l2_pm * inv;
        let a_pm = a1_pm * factor + a2_pm * inv;
        let b_pm = b1_pm * factor + b2_pm * inv;

        // Unpremultiply
        let L = L_pm / result_alpha;
        let a = a_pm / result_alpha;
        let b = b_pm / result_alpha;

        // Convert back to RGB
        let mut rgb = oklab::oklab_to_rgb(L, a, b);
        rgb.a = result_alpha;

        // Convert RGB to HSLA
        rgb.into()
    }

    fn to_hex(&self) -> String {
        let rgb = self.to_rgb();

        if rgb.a < 1. {
            return format!(
                "#{:02X}{:02X}{:02X}{:02X}",
                ((rgb.r * 255.) as u32),
                ((rgb.g * 255.) as u32),
                ((rgb.b * 255.) as u32),
                ((self.a * 255.) as u32)
            );
        }

        format!(
            "#{:02X}{:02X}{:02X}",
            ((rgb.r * 255.) as u32),
            ((rgb.g * 255.) as u32),
            ((rgb.b * 255.) as u32)
        )
    }

    fn parse_hex(hex: &str) -> Result<Self> {
        let hex = hex.trim_start_matches('#');
        let len = hex.len();
        if len != 6 && len != 8 {
            return Err(anyhow::anyhow!("invalid hex color"));
        }

        let r = u8::from_str_radix(&hex[0..2], 16)? as f32 / 255.;
        let g = u8::from_str_radix(&hex[2..4], 16)? as f32 / 255.;
        let b = u8::from_str_radix(&hex[4..6], 16)? as f32 / 255.;
        let a = if len == 8 {
            u8::from_str_radix(&hex[6..8], 16)? as f32 / 255.
        } else {
            1.
        };

        let v = gpui::Rgba { r, g, b, a };
        let color: Hsla = v.into();
        Ok(color)
    }

    fn hue(&self, hue: f32) -> Self {
        let mut color = *self;
        color.h = hue.clamp(0., 1.);
        color
    }

    fn saturation(&self, saturation: f32) -> Self {
        let mut color = *self;
        color.s = saturation.clamp(0., 1.);
        color
    }

    fn lightness(&self, lightness: f32) -> Self {
        let mut color = *self;
        color.l = lightness.clamp(0., 1.);
        color
    }
}

pub(crate) static DEFAULT_COLORS: once_cell::sync::Lazy<ShadcnColors> =
    once_cell::sync::Lazy::new(|| {
        serde_json::from_str(include_str!("./default-colors.json"))
            .expect("failed to parse default-colors.json")
    });

type ColorScales = HashMap<usize, ShadcnColor>;

mod color_scales {
    use std::collections::HashMap;

    use super::{ColorScales, ShadcnColor};

    use serde::de::{Deserialize, Deserializer};

    pub fn deserialize<'de, D>(deserializer: D) -> Result<ColorScales, D::Error>
    where
        D: Deserializer<'de>,
    {
        let mut map = HashMap::new();
        for color in Vec::<ShadcnColor>::deserialize(deserializer)? {
            map.insert(color.scale, color);
        }
        Ok(map)
    }
}

/// Enum representing the available color names.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ColorName {
    White,
    Black,
    Neutral,
    Gray,
    Red,
    Orange,
    Amber,
    Yellow,
    Lime,
    Green,
    Emerald,
    Teal,
    Cyan,
    Sky,
    Blue,
    Indigo,
    Violet,
    Purple,
    Fuchsia,
    Pink,
    Rose,
}

impl Display for ColorName {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?}", self)
    }
}

// Strict color name parser.
impl TryFrom<&str> for ColorName {
    type Error = anyhow::Error;
    fn try_from(value: &str) -> std::result::Result<Self, Self::Error> {
        match value.to_lowercase().as_str() {
            "white" => Ok(ColorName::White),
            "black" => Ok(ColorName::Black),
            "neutral" => Ok(ColorName::Neutral),
            "gray" => Ok(ColorName::Gray),
            "red" => Ok(ColorName::Red),
            "orange" => Ok(ColorName::Orange),
            "amber" => Ok(ColorName::Amber),
            "yellow" => Ok(ColorName::Yellow),
            "lime" => Ok(ColorName::Lime),
            "green" => Ok(ColorName::Green),
            "emerald" => Ok(ColorName::Emerald),
            "teal" => Ok(ColorName::Teal),
            "cyan" => Ok(ColorName::Cyan),
            "sky" => Ok(ColorName::Sky),
            "blue" => Ok(ColorName::Blue),
            "indigo" => Ok(ColorName::Indigo),
            "violet" => Ok(ColorName::Violet),
            "purple" => Ok(ColorName::Purple),
            "fuchsia" => Ok(ColorName::Fuchsia),
            "pink" => Ok(ColorName::Pink),
            "rose" => Ok(ColorName::Rose),
            _ => Err(anyhow::anyhow!("Invalid color name")),
        }
    }
}

impl TryFrom<SharedString> for ColorName {
    type Error = anyhow::Error;
    fn try_from(value: SharedString) -> std::result::Result<Self, Self::Error> {
        value.as_ref().try_into()
    }
}

impl ColorName {
    /// Returns all available color names.
    pub fn all() -> [Self; 19] {
        [
            ColorName::Neutral,
            ColorName::Gray,
            ColorName::Red,
            ColorName::Orange,
            ColorName::Amber,
            ColorName::Yellow,
            ColorName::Lime,
            ColorName::Green,
            ColorName::Emerald,
            ColorName::Teal,
            ColorName::Cyan,
            ColorName::Sky,
            ColorName::Blue,
            ColorName::Indigo,
            ColorName::Violet,
            ColorName::Purple,
            ColorName::Fuchsia,
            ColorName::Pink,
            ColorName::Rose,
        ]
    }

    /// Returns the color for the given scale.
    ///
    /// The `scale` is any of `[50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]`
    /// falls back to 500 if out of range.
    pub fn scale(&self, scale: usize) -> Hsla {
        if self == &ColorName::White {
            return DEFAULT_COLORS.white.hsla;
        }
        if self == &ColorName::Black {
            return DEFAULT_COLORS.black.hsla;
        }

        let colors = match self {
            ColorName::Neutral => &DEFAULT_COLORS.neutral,
            ColorName::Gray => &DEFAULT_COLORS.gray,
            ColorName::Red => &DEFAULT_COLORS.red,
            ColorName::Orange => &DEFAULT_COLORS.orange,
            ColorName::Amber => &DEFAULT_COLORS.amber,
            ColorName::Yellow => &DEFAULT_COLORS.yellow,
            ColorName::Lime => &DEFAULT_COLORS.lime,
            ColorName::Green => &DEFAULT_COLORS.green,
            ColorName::Emerald => &DEFAULT_COLORS.emerald,
            ColorName::Teal => &DEFAULT_COLORS.teal,
            ColorName::Cyan => &DEFAULT_COLORS.cyan,
            ColorName::Sky => &DEFAULT_COLORS.sky,
            ColorName::Blue => &DEFAULT_COLORS.blue,
            ColorName::Indigo => &DEFAULT_COLORS.indigo,
            ColorName::Violet => &DEFAULT_COLORS.violet,
            ColorName::Purple => &DEFAULT_COLORS.purple,
            ColorName::Fuchsia => &DEFAULT_COLORS.fuchsia,
            ColorName::Pink => &DEFAULT_COLORS.pink,
            ColorName::Rose => &DEFAULT_COLORS.rose,
            _ => unreachable!(),
        };

        if let Some(color) = colors.get(&scale) {
            color.hsla
        } else {
            colors.get(&500).unwrap().hsla
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Deserialize)]
pub(crate) struct ShadcnColors {
    pub(crate) black: ShadcnColor,
    pub(crate) white: ShadcnColor,
    #[serde(with = "color_scales")]
    pub(crate) slate: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) gray: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) zinc: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) neutral: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) stone: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) red: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) orange: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) amber: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) yellow: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) lime: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) green: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) emerald: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) teal: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) cyan: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) sky: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) blue: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) indigo: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) violet: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) purple: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) fuchsia: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) pink: ColorScales,
    #[serde(with = "color_scales")]
    pub(crate) rose: ColorScales,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, serde::Deserialize)]
pub(crate) struct ShadcnColor {
    #[serde(default)]
    pub(crate) scale: usize,
    #[serde(deserialize_with = "from_hsl_channel", alias = "hslChannel")]
    pub(crate) hsla: Hsla,
}

/// Deserialize Hsla from a string in the format "210 40% 98%"
fn from_hsl_channel<'de, D>(deserializer: D) -> Result<Hsla, D::Error>
where
    D: Deserializer<'de>,
{
    let s: String = Deserialize::deserialize(deserializer).unwrap();

    let mut parts = s.split_whitespace();
    if parts.clone().count() != 3 {
        return Err(D::Error::custom(
            "expected hslChannel has 3 parts, e.g: '210 40% 98%'",
        ));
    }

    fn parse_number(s: &str) -> f32 {
        s.trim_end_matches('%')
            .parse()
            .expect("failed to parse number")
    }

    let (h, s, l) = (
        parse_number(parts.next().unwrap()),
        parse_number(parts.next().unwrap()),
        parse_number(parts.next().unwrap()),
    );

    Ok(hsl(h, s, l))
}

macro_rules! color_method {
    ($color:tt, $scale:tt) => {
        paste::paste! {
            #[inline]
            #[allow(unused)]
            pub fn [<$color _ $scale>]() -> Hsla {
                if let Some(color) = DEFAULT_COLORS.$color.get(&($scale as usize)) {
                    return color.hsla;
                }

                black()
            }
        }
    };
}

macro_rules! color_methods {
    ($color:tt) => {
        paste::paste! {
            /// Get color by scale number.
            ///
            /// The possible scale numbers are:
            /// 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950
            ///
            /// If the scale number is not found, it will return black color.
            #[inline]
            pub fn [<$color>](scale: usize) -> Hsla {
                if let Some(color) = DEFAULT_COLORS.$color.get(&scale) {
                    return color.hsla;
                }

                black()
            }
        }

        color_method!($color, 50);
        color_method!($color, 100);
        color_method!($color, 200);
        color_method!($color, 300);
        color_method!($color, 400);
        color_method!($color, 500);
        color_method!($color, 600);
        color_method!($color, 700);
        color_method!($color, 800);
        color_method!($color, 900);
        color_method!($color, 950);
    };
}

pub fn black() -> Hsla {
    DEFAULT_COLORS.black.hsla
}

pub fn white() -> Hsla {
    DEFAULT_COLORS.white.hsla
}

color_methods!(slate);
color_methods!(gray);
color_methods!(zinc);
color_methods!(neutral);
color_methods!(stone);
color_methods!(red);
color_methods!(orange);
color_methods!(amber);
color_methods!(yellow);
color_methods!(lime);
color_methods!(green);
color_methods!(emerald);
color_methods!(teal);
color_methods!(cyan);
color_methods!(sky);
color_methods!(blue);
color_methods!(indigo);
color_methods!(violet);
color_methods!(purple);
color_methods!(fuchsia);
color_methods!(pink);
color_methods!(rose);

/// Try to parse the color, HEX or [Tailwind Color](https://tailwindcss.com/docs/colors) expression.
///
/// # Parameter `color` should be one string value listed below:
///
/// - `#RRGGBB` - The HEX color string.
/// - `#RRGGBBAA` - The HEX color string with alpha.
///
/// Or the Tailwind Color format:
///
/// - `name` - The color name `black`, `white`, or any other defined in `crate::color`.
/// - `name-scale` - The color name with scale.
/// - `name/opacity` - The color name with opacity, `opacity` should be an integer between 0 and 100.
/// - `name-scale/opacity` - The color name with scale and opacity.
///
pub fn try_parse_color(color: &str) -> Result<Hsla> {
    if color.starts_with("#") {
        let rgba = gpui::Rgba::try_from(color)?;
        return Ok(rgba.into());
    }

    let mut name = String::new();
    let mut scale = None;
    let mut opacity = None;
    // 0: name, 1: scale, 2: opacity
    let mut state = 0;
    let mut part = String::new();

    for c in color.chars() {
        match c {
            '-' if state == 0 => {
                name = std::mem::take(&mut part);
                state = 1;
            }
            '/' if state <= 1 => {
                if state == 0 {
                    name = std::mem::take(&mut part);
                } else if state == 1 {
                    scale = part.parse::<usize>().ok();
                    part.clear();
                }
                state = 2;
            }
            _ => part.push(c),
        }
    }

    match state {
        0 => name = part,
        1 => scale = part.parse::<usize>().ok(),
        2 => opacity = part.parse::<f32>().ok(),
        _ => {}
    }

    if name.is_empty() {
        return Err(anyhow!("Empty color name"));
    }

    let mut hsla = match name.as_str() {
        "black" => Ok::<Hsla, Error>(crate::black()),
        "white" => Ok(crate::white()),
        _ => {
            let color_name = ColorName::try_from(name.as_str())?;
            if let Some(scale) = scale {
                Ok(color_name.scale(scale))
            } else {
                Ok(color_name.scale(500))
            }
        }
    }?;

    if let Some(opacity) = opacity {
        if opacity > 100. {
            return Err(anyhow!("Invalid color opacity"));
        }
        hsla = hsla.opacity(opacity / 100.);
    }

    Ok(hsla)
}

/// Try to parse a theme background value.
///
/// Supports all values accepted by [`try_parse_color`] and CSS-style two-stop
/// `linear-gradient(...)` values.
pub fn try_parse_background(background: &str) -> Result<Background> {
    if let Ok(color) = try_parse_color(background) {
        return Ok(color.into());
    }

    let gradient = parse_linear_gradient(background)?;
    Ok(linear_gradient(gradient.angle, gradient.from, gradient.to))
}

/// Parse a background, clamping every color stop's alpha to at most `max`.
///
/// Unlike [`Background::opacity`], which scales all stops by a single factor,
/// this caps each gradient stop independently, so a bright `to` stop (or a
/// transparent `from` stop) can never push the rendered highlight past `max`.
pub(crate) fn try_parse_background_clamped(background: &str, max: f32) -> Result<Background> {
    if let Ok(color) = try_parse_color(background) {
        return Ok(color.alpha(color.a.min(max)).into());
    }

    let gradient = parse_linear_gradient(background)?;
    let clamp = |stop: LinearColorStop| {
        linear_color_stop(stop.color.alpha(stop.color.a.min(max)), stop.percentage)
    };
    Ok(linear_gradient(
        gradient.angle,
        clamp(gradient.from),
        clamp(gradient.to),
    ))
}

pub(crate) fn try_parse_theme_color(color: &str) -> Result<Hsla> {
    if let Ok(color) = try_parse_color(color) {
        return Ok(color);
    }

    Ok(parse_linear_gradient(color)?.from.color)
}

struct ParsedLinearGradient {
    angle: f32,
    from: LinearColorStop,
    to: LinearColorStop,
}

fn parse_linear_gradient(background: &str) -> Result<ParsedLinearGradient> {
    const PREFIX: &str = "linear-gradient(";

    let background = background.trim();
    if !background.to_ascii_lowercase().starts_with(PREFIX) || !background.ends_with(')') {
        return Err(anyhow!("Unsupported background value"));
    }

    let inner = &background[PREFIX.len()..background.len() - 1];
    let parts = split_top_level_commas(inner);
    let (angle, from, to) = match parts.as_slice() {
        [from, to] => (
            180.,
            parse_linear_color_stop(from, 0.)?,
            parse_linear_color_stop(to, 1.)?,
        ),
        [angle, from, to] => (
            parse_linear_gradient_angle(angle)?,
            parse_linear_color_stop(from, 0.)?,
            parse_linear_color_stop(to, 1.)?,
        ),
        _ => {
            return Err(anyhow!(
                "Expected linear-gradient with two color stops, e.g. linear-gradient(135deg, #000, #fff)"
            ));
        }
    };

    Ok(ParsedLinearGradient { angle, from, to })
}

fn split_top_level_commas(value: &str) -> Vec<String> {
    let mut parts = Vec::new();
    let mut depth = 0usize;
    let mut start = 0usize;

    for (ix, ch) in value.char_indices() {
        match ch {
            '(' => depth += 1,
            ')' => depth = depth.saturating_sub(1),
            ',' if depth == 0 => {
                parts.push(value[start..ix].trim().to_string());
                start = ix + ch.len_utf8();
            }
            _ => {}
        }
    }

    parts.push(value[start..].trim().to_string());
    parts
}

fn parse_linear_gradient_angle(angle: &str) -> Result<f32> {
    let angle = angle.trim().to_ascii_lowercase();

    if let Some(degrees) = angle.strip_suffix("deg") {
        return Ok(degrees.trim().parse::<f32>()?.rem_euclid(360.));
    }

    if let Some(direction) = angle.strip_prefix("to ") {
        return parse_linear_gradient_direction(direction);
    }

    Err(anyhow!("Unsupported linear-gradient angle: {angle}"))
}

fn parse_linear_gradient_direction(direction: &str) -> Result<f32> {
    let mut top = false;
    let mut right = false;
    let mut bottom = false;
    let mut left = false;

    for part in direction.split_whitespace() {
        match part {
            "top" => top = true,
            "right" => right = true,
            "bottom" => bottom = true,
            "left" => left = true,
            _ => {
                return Err(anyhow!(
                    "Unsupported linear-gradient direction: {direction}"
                ));
            }
        }
    }

    match (top, right, bottom, left) {
        (true, false, false, false) => Ok(0.),
        (false, true, false, false) => Ok(90.),
        (false, false, true, false) => Ok(180.),
        (false, false, false, true) => Ok(270.),
        (true, true, false, false) => Ok(45.),
        (false, true, true, false) => Ok(135.),
        (false, false, true, true) => Ok(225.),
        (true, false, false, true) => Ok(315.),
        _ => Err(anyhow!(
            "Unsupported linear-gradient direction: {direction}"
        )),
    }
}

fn parse_linear_color_stop(stop: &str, default_percentage: f32) -> Result<LinearColorStop> {
    let stop = stop.trim();
    let mut parts = stop.split_whitespace().collect::<Vec<_>>();
    let percentage = parts
        .last()
        .and_then(|part| part.strip_suffix('%'))
        .map(|part| part.parse::<f32>().map(|value| value / 100.))
        .transpose()?
        .unwrap_or(default_percentage);

    if stop.ends_with('%') {
        parts.pop();
    }

    let color = parts.join(" ");
    if color.is_empty() {
        return Err(anyhow!("Expected color in linear-gradient color stop"));
    }

    Ok(linear_color_stop(
        try_parse_color(&color)?,
        percentage.clamp(0., 1.),
    ))
}

#[cfg(test)]
mod tests {
    use gpui::{rgb, rgba};

    use super::*;

    #[test]
    fn test_default_colors() {
        assert_eq!(white(), hsl(0.0, 0.0, 100.0));
        assert_eq!(black(), hsl(0.0, 0.0, 0.0));

        assert_eq!(slate_50(), hsl(210.0, 40.0, 98.0));
        assert_eq!(slate_100(), hsl(210.0, 40.0, 96.1));
        assert_eq!(slate_900(), hsl(222.2, 47.4, 11.2));

        assert_eq!(red_50(), hsl(0.0, 85.7, 97.3));
        assert_eq!(yellow_100(), hsl(54.9, 96.7, 88.0));
        assert_eq!(green_200(), hsl(141.0, 78.9, 85.1));
        assert_eq!(cyan_300(), hsl(187.0, 92.4, 69.0));
        assert_eq!(blue_400(), hsl(213.1, 93.9, 67.8));
        assert_eq!(indigo_500(), hsl(238.7, 83.5, 66.7));
    }

    #[test]
    fn test_to_hex_string() {
        let color: Hsla = rgb(0xf8fafc).into();
        assert_eq!(color.to_hex(), "#F8FAFC");

        let color: Hsla = rgb(0xfef2f2).into();
        assert_eq!(color.to_hex(), "#FEF2F2");

        let color: Hsla = rgba(0x0413fcaa).into();
        assert_eq!(color.to_hex(), "#0413FCAA");
    }

    #[test]
    fn test_from_hex_string() {
        let color: Hsla = Hsla::parse_hex("#F8FAFC").unwrap();
        assert_eq!(color, rgb(0xf8fafc).into());

        let color: Hsla = Hsla::parse_hex("#FEF2F2").unwrap();
        assert_eq!(color, rgb(0xfef2f2).into());

        let color: Hsla = Hsla::parse_hex("#0413FCAA").unwrap();
        assert_eq!(color, rgba(0x0413fcaa).into());
    }

    #[test]
    fn test_lighten() {
        let color = super::hsl(240.0, 5.0, 30.0);
        let color = color.lighten(0.5);
        assert_eq!(color.l, 0.45000002);
        let color = color.lighten(0.5);
        assert_eq!(color.l, 0.675);
        let color = color.lighten(0.1);
        assert_eq!(color.l, 0.7425);
    }

    #[test]
    fn test_darken() {
        let color = super::hsl(240.0, 5.0, 96.0);
        let color = color.darken(0.5);
        assert_eq!(color.l, 0.48);
        let color = color.darken(0.5);
        assert_eq!(color.l, 0.24);
    }

    #[test]
    fn test_mix() {
        let red = Hsla::parse_hex("#FF0000").unwrap();
        let blue = Hsla::parse_hex("#0000FF").unwrap();
        let green = Hsla::parse_hex("#00FF00").unwrap();
        let yellow = Hsla::parse_hex("#FFFF00").unwrap();

        assert_eq!(red.mix(blue, 0.5).to_hex(), "#FF00FF");
        assert_eq!(green.mix(red, 0.5).to_hex(), "#FFFF00");
        assert_eq!(blue.mix(yellow, 0.2).to_hex(), "#0098FF");
    }

    #[test]
    fn test_mix_oklab() {
        let red = Hsla::parse_hex("#FF0000").unwrap();
        let blue = Hsla::parse_hex("#0000FF").unwrap();
        let transparent = gpui::Hsla {
            h: 0.0,
            s: 0.0,
            l: 0.0,
            a: 0.0,
        };

        // Test mixing red with transparent (similar to CSS color-mix example)
        // color-mix(in oklab, red 20%, transparent) should give red with 20% opacity
        let result = red.mix_oklab(transparent, 0.2);
        assert!((result.a - 0.2).abs() < 0.01); // Alpha should be 20%

        // The color should remain red (hue should be preserved)
        let rgb_result = result.to_rgb();
        let rgb_red = red.to_rgb();
        // Allow some tolerance due to color space conversions
        assert!(
            (rgb_result.r - rgb_red.r).abs() < 0.05,
            "Red channel should be preserved"
        );
        assert!(rgb_result.g < 0.05, "Green channel should be near 0");
        assert!(rgb_result.b < 0.05, "Blue channel should be near 0");

        // Test basic color mixing in Oklab space
        let purple = red.mix_oklab(blue, 0.5);
        // Oklab mixing should produce different results than HSL mixing
        let purple_hsl = red.mix(blue, 0.5);
        assert_ne!(purple.to_hex(), purple_hsl.to_hex());

        // Test factor boundaries (allowing small floating point errors)
        let result_0 = red.mix_oklab(blue, 0.0);
        let result_1 = red.mix_oklab(blue, 1.0);

        // Check that result is close to expected (within 1 color unit per channel)
        let rgb_0 = result_0.to_rgb();
        let rgb_blue = blue.to_rgb();
        assert!((rgb_0.r - rgb_blue.r).abs() < 0.01);
        assert!((rgb_0.g - rgb_blue.g).abs() < 0.01);
        assert!((rgb_0.b - rgb_blue.b).abs() < 0.01);

        let rgb_1 = result_1.to_rgb();
        let rgb_red = red.to_rgb();
        assert!((rgb_1.r - rgb_red.r).abs() < 0.01);
        assert!((rgb_1.g - rgb_red.g).abs() < 0.01);
        assert!((rgb_1.b - rgb_red.b).abs() < 0.01);
    }

    #[test]
    fn test_color_name() {
        assert_eq!(ColorName::Purple.to_string(), "Purple");
        assert_eq!(format!("{}", ColorName::Green), "Green");
        assert_eq!(format!("{:?}", ColorName::Yellow), "Yellow");

        let color = ColorName::Green;
        assert_eq!(color.scale(500).to_hex(), "#21C55E");
        assert_eq!(color.scale(1500).to_hex(), "#21C55E");

        for name in ColorName::all().iter() {
            let name1: ColorName = name.to_string().as_str().try_into().unwrap();
            assert_eq!(name1, *name);
        }
    }

    #[test]
    fn test_h_s_l() {
        let color = hsl(260., 94., 80.);
        assert_eq!(color.hue(200. / 360.), hsl(200., 94., 80.));
        assert_eq!(color.saturation(74. / 100.), hsl(260., 74., 80.));
        assert_eq!(color.lightness(74. / 100.), hsl(260., 94., 74.));
    }

    #[test]
    fn test_try_parse_color() {
        assert_eq!(
            try_parse_color("#F2F200").ok(),
            Some(hsla(0.16666667, 1., 0.4745098, 1.0))
        );
        assert_eq!(
            try_parse_color("#00f21888").ok(),
            Some(hsla(0.34986225, 1.0, 0.4745098, 0.53333336))
        );
        assert_eq!(try_parse_color("black").ok(), Some(crate::black()));
        assert_eq!(try_parse_color("white-800").ok(), Some(crate::white()));
        assert_eq!(try_parse_color("red").ok(), Some(crate::red_500()));
        assert_eq!(try_parse_color("blue-600").ok(), Some(crate::blue_600()));
        assert_eq!(
            try_parse_color("pink/33").ok(),
            Some(crate::pink_500().opacity(0.33))
        );
        assert_eq!(
            try_parse_color("orange-300/66").ok(),
            Some(crate::orange_300().opacity(0.66))
        );
    }

    #[test]
    fn test_try_parse_background_linear_gradient() {
        let from = try_parse_color("#4F46E5").unwrap();
        let to = try_parse_color("#06B6D4").unwrap();

        assert_eq!(
            try_parse_background("linear-gradient(135deg, #4F46E5, #06B6D4)").unwrap(),
            gpui::linear_gradient(
                135.,
                gpui::linear_color_stop(from, 0.),
                gpui::linear_color_stop(to, 1.)
            )
        );
    }

    #[test]
    fn test_try_parse_background_linear_gradient_direction_and_stops() {
        assert_eq!(
            try_parse_background("linear-gradient(to right, red-500 25%, blue-600 75%)").unwrap(),
            gpui::linear_gradient(
                90.,
                gpui::linear_color_stop(crate::red_500(), 0.25),
                gpui::linear_color_stop(crate::blue_600(), 0.75)
            )
        );
    }
}
