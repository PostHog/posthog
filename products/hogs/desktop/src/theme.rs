use gpui_kit::{Rgba, WindowAppearance, rgb};

/// The app's colors for one system appearance.
#[derive(Clone, Copy)]
pub struct Palette {
    pub panel: Rgba,
    pub surface: Rgba,
    pub canvas: Rgba,
    pub bubble_in: Rgba,
    pub bubble_out: Rgba,
    pub text: Rgba,
    pub text_2: Rgba,
    pub text_3: Rgba,
    pub divider: Rgba,
    pub selected: Rgba,
    pub hover: Rgba,
    pub accent: Rgba,
    pub badge: Rgba,
    pub badge_text: Rgba,
    pub tick_seen: Rgba,
    pub danger: Rgba,
    pub scrim: Rgba,
}

impl Palette {
    pub fn for_appearance(appearance: WindowAppearance) -> Self {
        match appearance {
            WindowAppearance::Dark | WindowAppearance::VibrantDark => Self {
                panel: rgb(0x111B21),
                surface: rgb(0x202C33),
                canvas: rgb(0x0B141A),
                bubble_in: rgb(0x202C33),
                bubble_out: rgb(0x005C4B),
                text: rgb(0xE9EDEF),
                text_2: rgb(0xD1D7DB),
                text_3: rgb(0x8696A0),
                divider: rgb(0x222D34),
                selected: rgb(0x2A3942),
                hover: rgb(0x202C33),
                accent: rgb(0x00A884),
                badge: rgb(0x00A884),
                badge_text: rgb(0x111B21),
                tick_seen: rgb(0x53BDEB),
                danger: rgb(0xF15C6D),
                scrim: Rgba { r: 0.04, g: 0.08, b: 0.1, a: 0.6 },
            },
            _ => Self {
                panel: rgb(0xFFFFFF),
                surface: rgb(0xF0F2F5),
                canvas: rgb(0xEFEAE2),
                bubble_in: rgb(0xFFFFFF),
                bubble_out: rgb(0xD9FDD3),
                text: rgb(0x111B21),
                text_2: rgb(0x3B4A54),
                text_3: rgb(0x667781),
                divider: rgb(0xE9EDEF),
                selected: rgb(0xF0F2F5),
                hover: rgb(0xF5F6F6),
                accent: rgb(0x00A884),
                badge: rgb(0x25D366),
                badge_text: rgb(0xFFFFFF),
                tick_seen: rgb(0x53BDEB),
                danger: rgb(0xD93F3F),
                scrim: Rgba { r: 0.04, g: 0.08, b: 0.1, a: 0.45 },
            },
        }
    }
}

/// Parses "#RRGGBB". Anything else falls back to the accent green.
pub fn hex(color: &str) -> Rgba {
    u32::from_str_radix(color.trim_start_matches('#'), 16).map(rgb).unwrap_or(rgb(0x00A884))
}

pub const EMOJI: [&str; 12] = ["🦔", "🔭", "🛎️", "📈", "🐛", "🧪", "💸", "🛡️", "📬", "🧹", "🚀", "🦉"];
pub const COLORS: [&str; 8] =
    ["#00A884", "#F54E00", "#1D4AFF", "#B62AD9", "#DC9300", "#E0457B", "#2F80ED", "#5F6B7A"];
