pub type Palette = [u32; 14];

pub struct Preset {
    pub name: &'static str,
    pub detail: &'static str,
    pub light: Palette,
    pub dark: Palette,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Mode {
    System,
    Light,
    Dark,
}

impl Mode {
    pub const ALL: [Mode; 3] = [Mode::System, Mode::Light, Mode::Dark];

    pub fn label(self) -> &'static str {
        match self {
            Mode::System => "System",
            Mode::Light => "Light",
            Mode::Dark => "Dark",
        }
    }
}

pub const PRESETS: [Preset; 3] = [
    Preset {
        name: "Neutral",
        detail: "Quiet and monochrome",
        light: crate::design::LIGHT,
        dark: crate::design::GRAPHITE,
    },
    Preset {
        name: "Warm",
        detail: "Paper and charcoal",
        light: [
            0x2b2722, 0x564f47, 0x71695f, 0xfaf7f1, 0xf2ede4, 0xe5ddce, 0xf4efe6, 0xe2d9ca,
            0xa8463a, 0x4c7a55, 0x8a5a3c, 0x9c6328, 0x77608a, 0xffffff,
        ],
        dark: [
            0xf0eae5, 0xb3a79e, 0x948980, 0x1c1917, 0x25211f, 0x37302c, 0x151211, 0x332b27,
            0xe5807a, 0x93c7a0, 0xe0a48a, 0xdcb072, 0xbfa6d6, 0x2a140b,
        ],
    },
    Preset {
        name: "Cool",
        detail: "Morning mist and ink blue",
        light: [
            0x1e232d, 0x4b5362, 0x666e7b, 0xfafbfc, 0xf1f3f6, 0xe3e6ec, 0xf3f5f8, 0xdadee5,
            0xb0443f, 0x3b7a5a, 0x4a5a82, 0x9e652a, 0x6c5a9e, 0xffffff,
        ],
        dark: [
            0xe4e8ef, 0x9aa4b5, 0x7e8797, 0x10141c, 0x181d27, 0x262d3a, 0x0b0e14, 0x222a38,
            0xe58088, 0x7cc7a2, 0x9db4e8, 0xdcae74, 0xab9fdc, 0x0c1424,
        ],
    },
];

const RETIRED: [(&str, usize, Mode); 9] = [
    ("Light", 0, Mode::Light),
    ("Graphite", 0, Mode::Dark),
    ("Paper", 1, Mode::Light),
    ("Ember", 1, Mode::Dark),
    ("Dusk", 1, Mode::Dark),
    ("Mist", 2, Mode::Light),
    ("Midnight", 2, Mode::Dark),
    ("Fjord", 2, Mode::Dark),
    ("Forest", 2, Mode::Dark),
];

pub fn parse(scheme: Option<&str>) -> (&'static Preset, Mode) {
    let Some(scheme) = scheme else {
        return (&PRESETS[0], Mode::System);
    };
    if let Some((_, index, mode)) = RETIRED.iter().find(|(name, ..)| *name == scheme) {
        return (&PRESETS[*index], *mode);
    }
    let (name, mode) = match scheme.split_once('/') {
        Some((name, "light")) => (name, Mode::Light),
        Some((name, "dark")) => (name, Mode::Dark),
        Some((name, _)) => (name, Mode::System),
        None => (scheme, Mode::System),
    };
    match PRESETS.iter().find(|p| p.name == name) {
        Some(preset) => (preset, mode),
        None => (&PRESETS[0], Mode::System),
    }
}

pub fn scheme(preset: &Preset, mode: Mode) -> Option<String> {
    match mode {
        Mode::System if preset.name == PRESETS[0].name => None,
        Mode::System => Some(preset.name.to_owned()),
        Mode::Light => Some(format!("{}/light", preset.name)),
        Mode::Dark => Some(format!("{}/dark", preset.name)),
    }
}

pub fn palette(preset: &Preset, mode: Mode, system_dark: bool) -> Palette {
    let dark = match mode {
        Mode::System => system_dark,
        Mode::Light => false,
        Mode::Dark => true,
    };
    if dark { preset.dark } else { preset.light }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retired_and_new_schemes_resolve_to_a_family_and_mode() {
        for (scheme, family, mode) in [
            (None, "Neutral", Mode::System),
            (Some("Graphite"), "Neutral", Mode::Dark),
            (Some("Paper"), "Warm", Mode::Light),
            (Some("Fjord"), "Cool", Mode::Dark),
            (Some("Warm"), "Warm", Mode::System),
            (Some("Cool/light"), "Cool", Mode::Light),
            (Some("Unknown"), "Neutral", Mode::System),
        ] {
            let (preset, parsed) = parse(scheme);
            assert_eq!((preset.name, parsed), (family, mode), "{scheme:?}");
            let saved = super::scheme(preset, parsed);
            let (again, again_mode) = parse(saved.as_deref());
            assert_eq!((again.name, again_mode), (family, mode));
        }
    }

    #[test]
    fn faint_text_is_readable_on_every_surface() {
        fn luminance(c: u32) -> f64 {
            let channel = |shift: u32| {
                let x = f64::from((c >> shift) & 255) / 255.;
                if x <= 0.03928 {
                    x / 12.92
                } else {
                    ((x + 0.055) / 1.055).powf(2.4)
                }
            };
            0.2126 * channel(16) + 0.7152 * channel(8) + 0.0722 * channel(0)
        }
        fn contrast(a: u32, b: u32) -> f64 {
            let (a, b) = (luminance(a), luminance(b));
            (a.max(b) + 0.05) / (a.min(b) + 0.05)
        }
        for preset in &PRESETS {
            for palette in [preset.light, preset.dark] {
                for surface in [palette[3], palette[4], palette[6]] {
                    assert!(contrast(palette[2], surface) >= 4.5, "{}", preset.name);
                }
                assert!(contrast(palette[7], palette[6]) >= 1.2, "{}", preset.name);
            }
        }
    }
}
