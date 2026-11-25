//! Persisted application design tokens and shared live color palette.
//! Updates are private host actions and cannot change view permissions.
use serde::{Deserialize, Serialize};
use std::cell::Cell;

pub const BODY: f32 = 13.;
pub const CAPTION: f32 = 11.5;
pub const TITLE: f32 = 18.;
pub const PAGE_INSET: f32 = 24.;
pub const NAV_ROW: f32 = 30.;

/// Native sidebar badge normalization, also used for browser script badges.
pub fn badge_text(value: serde_json::Value) -> Option<String> {
    let value = if value.is_object() {
        value["value"].clone()
    } else {
        value
    };
    let text = match value {
        serde_json::Value::Number(n) if n.as_f64() == Some(0.) => return None,
        serde_json::Value::Number(n) if n.as_f64().is_some_and(|n| n > 99.) => "99+".into(),
        serde_json::Value::Number(n) => n.to_string(),
        serde_json::Value::String(s) => s.trim().to_owned(),
        _ => return None,
    };
    let text: String = text.chars().take(4).collect();
    (!text.is_empty()).then_some(text)
}

/// The Light theme, and what a new install starts with. `theme::DEFAULT` is
/// the older blue-accented palette: it stays as the lookup table that maps the
/// SDK's color constants to palette slots.
pub const LIGHT: [u32; 14] = [
    0x1d1d1f, 0x55555a, 0x6e6e73, 0xffffff, 0xf5f5f6, 0xe6e6e8, 0xf5f5f6, 0xe7e7e9, 0xb3403a,
    0x3f7d57, 0x2c2c30, 0xa9682a, 0x6f5a9c, 0xffffff,
];
/// The Graphite theme: View's neutral dark, and what the web preview shows
/// when the visitor's system is in dark mode.
pub const GRAPHITE: [u32; 14] = [
    0xececee, 0xb4b4ba, 0x8a8a92, 0x1b1b1d, 0x222225, 0x2d2d31, 0x141415, 0x222225, 0xe5786d,
    0x7fc39a, 0xe4e4e7, 0xd9a868, 0xa99bd6, 0x18181a,
];
const EARLIER_LIGHT_SURFACES: [u32; 5] = [0xffffff, 0xf6f6f7, 0xe8e8ea, 0xf7f7f8, 0xececee];
const EARLIER_GRAPHITE_SURFACES: [u32; 5] = [0x1a1a1c, 0x222225, 0x2e2e32, 0x141415, 0x2c2c30];
/// Earlier Light and Graphite palettes: text colors, surfaces, and the palette they became.
const RETIRED: [([u32; 3], [u32; 5], [u32; 14]); 4] = [
    (
        [0x1d1d1f, 0x6e6e73, 0x9a9aa0],
        EARLIER_LIGHT_SURFACES,
        LIGHT,
    ),
    (
        [0x1d1d1f, 0x55555a, 0x6e6e73],
        EARLIER_LIGHT_SURFACES,
        LIGHT,
    ),
    (
        [0xececee, 0xa1a1a8, 0x6f6f77],
        EARLIER_GRAPHITE_SURFACES,
        GRAPHITE,
    ),
    (
        [0xececee, 0xb4b4ba, 0x8a8a92],
        EARLIER_GRAPHITE_SURFACES,
        GRAPHITE,
    ),
];
#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Tokens {
    pub palette: [u32; 14],
    pub custom_palette: Option<[u32; 14]>,
    pub sidebar: f32,
    pub settings_sidebar: f32,
    pub view_sidebar: f32,
    pub agent_sidebar: f32,
    pub nav_row: f32,
    pub toolbar: f32,
    pub row: f32,
    pub page_padding: f32,
    pub title: f32,
    pub body: f32,
    pub description: f32,
    pub navigation: f32,
    pub secondary: u8,
    pub line: u8,
}
impl Default for Tokens {
    fn default() -> Self {
        Self {
            palette: LIGHT,
            custom_palette: None,
            sidebar: 232.,
            settings_sidebar: 216.,
            view_sidebar: 188.,
            agent_sidebar: 440.,
            nav_row: NAV_ROW,
            toolbar: 48.,
            row: 48.,
            page_padding: PAGE_INSET,
            title: TITLE,
            body: BODY,
            description: CAPTION,
            navigation: 13.,
            secondary: (crate::theme::DEFAULT[1] & 0xff) as u8,
            line: (crate::theme::DEFAULT[5] & 0xff) as u8,
        }
    }
}
impl Tokens {
    pub fn normalized(mut self) -> Self {
        let d = Self::default();
        // Settings saved with the first Light palette follow Light as it changes.
        if self.palette == crate::theme::DEFAULT {
            self.palette = LIGHT;
        }
        // Settings saved with an earlier Light or Graphite follow the current one.
        for (text, surfaces, current) in RETIRED {
            let surfaces_match =
                self.palette[3..8] == surfaces || self.palette[3..8] == current[3..8];
            if self.palette[..3] == text && surfaces_match && self.palette[8..] == current[8..] {
                self.palette = current;
            }
        }
        for (i, color) in self.palette.iter_mut().enumerate() {
            if *color > 0xffffff {
                *color = d.palette[i];
            }
        }
        if let Some(palette) = &mut self.custom_palette {
            for (i, color) in palette.iter_mut().enumerate() {
                if *color > 0xffffff {
                    *color = d.palette[i];
                }
            }
        }
        macro_rules! bound {
            ($field:ident,$min:expr,$max:expr) => {
                self.$field = if self.$field.is_finite() {
                    self.$field.clamp($min, $max)
                } else {
                    d.$field
                };
            };
        }
        bound!(sidebar, 180., 260.);
        bound!(settings_sidebar, 184., 260.);
        bound!(view_sidebar, 180., 240.);
        bound!(agent_sidebar, 300., 800.);
        bound!(nav_row, 28., 38.);
        bound!(toolbar, 44., 60.);
        bound!(row, 44., 72.);
        bound!(page_padding, 20., 44.);
        bound!(title, 18., 24.);
        bound!(body, 12., 15.);
        bound!(description, 11., 14.);
        bound!(navigation, 12., 15.);
        self.secondary = self.secondary.clamp(75, 120);
        self.line = self.line.clamp(210, 245);
        self
    }
}
thread_local! {static CURRENT:Cell<Tokens>=Cell::new(Tokens::default());}
pub fn current() -> Tokens {
    CURRENT.with(Cell::get)
}
pub fn set(tokens: Tokens) {
    let tokens = tokens.normalized();
    crate::theme::set(tokens.palette);
    CURRENT.with(|value| value.set(tokens));
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn old_settings_receive_default_palette() {
        let tokens: Tokens = serde_json::from_str(r#"{"body":14}"#).unwrap();
        assert_eq!(tokens.palette, LIGHT);
        assert_eq!(tokens.body, 14.);
    }
    #[test]
    fn earlier_light_and_graphite_follow_the_current_palette() {
        for (text, surfaces, current) in RETIRED {
            for earlier in [surfaces, current[3..8].try_into().unwrap()] {
                let mut tokens = Tokens {
                    palette: current,
                    ..Tokens::default()
                };
                tokens.palette[..3].copy_from_slice(&text);
                tokens.palette[3..8].copy_from_slice(&earlier);
                assert_eq!(tokens.normalized().palette, current);
            }
        }
    }
    #[test]
    fn palette_round_trips_and_resolves_live() {
        let mut tokens = Tokens::default();
        tokens.palette[0] = 0xeeeeee;
        tokens.palette[3] = 0x121212;
        tokens.palette[13] = 0x010203;
        let restored: Tokens =
            serde_json::from_value(serde_json::to_value(tokens).unwrap()).unwrap();
        set(restored);
        assert_eq!(crate::theme::named("ink"), Some(0xeeeeee));
        assert_eq!(crate::theme::color(crate::theme::DEFAULT[3]), 0x121212);
        assert_eq!(crate::theme::named("accentForeground"), Some(0x010203));
        set(Tokens::default());
    }
    #[test]
    fn invalid_palette_values_fall_back() {
        let mut tokens = Tokens::default();
        tokens.palette[0] = 0xffffffff;
        tokens.palette[3] = 0;
        let tokens = tokens.normalized();
        assert_eq!(tokens.palette[0], Tokens::default().palette[0]);
        assert_eq!(tokens.palette[3], 0);
    }
}

#[cfg(test)]
mod custom_theme_tests {
    use super::*;
    #[test]
    fn saved_custom_palette_round_trips_and_normalizes() {
        let mut custom = crate::theme::DEFAULT;
        custom[10] = 0x773399;
        let tokens = Tokens {
            custom_palette: Some(custom),
            ..Tokens::default()
        };
        let restored: Tokens =
            serde_json::from_value(serde_json::to_value(tokens).unwrap()).unwrap();
        assert_eq!(restored.custom_palette, Some(custom));
        custom[3] = 0xffffffff;
        let tokens = Tokens {
            custom_palette: Some(custom),
            ..tokens
        }
        .normalized();
        assert_eq!(tokens.custom_palette.unwrap()[3], crate::theme::DEFAULT[3]);
    }
}
