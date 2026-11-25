//! Original View palettes, with readable text and action pairs in both modes.
pub type Palette = [u32; 14];
pub struct Preset {
    pub name: &'static str,
    pub detail: &'static str,
    pub palette: Palette,
}
pub const PRESETS: [Preset; 9] = [
    Preset {
        name: "Light",
        detail: "Quiet and monochrome",
        palette: crate::design::LIGHT,
    },
    Preset {
        name: "Graphite",
        detail: "Neutral and deep",
        palette: crate::design::GRAPHITE,
    },
    Preset {
        name: "Paper",
        detail: "Warm and unhurried",
        palette: [
            0x2b2722, 0x6d655b, 0x968d80, 0xfaf7f1, 0xf2ede4, 0xe5ddce, 0xf4efe6, 0xe8dfcf,
            0xa8463a, 0x4c7a55, 0x8a5a3c, 0xa2672a, 0x77608a, 0xffffff,
        ],
    },
    Preset {
        name: "Mist",
        detail: "Cool morning light",
        palette: [
            0x1e232d, 0x5d6676, 0x8a93a2, 0xfafbfc, 0xf1f3f6, 0xe3e6ec, 0xf3f5f8, 0xe4e8ef,
            0xb0443f, 0x3b7a5a, 0x4a5a82, 0xa66a2c, 0x6c5a9e, 0xffffff,
        ],
    },
    Preset {
        name: "Midnight",
        detail: "Ink blue, soft periwinkle",
        palette: [
            0xe4e8ef, 0x9aa4b5, 0x6a7486, 0x10141c, 0x181d27, 0x262d3a, 0x0b0e14, 0x222a38,
            0xe58088, 0x7cc7a2, 0x9db4e8, 0xdcae74, 0xab9fdc, 0x0c1424,
        ],
    },
    Preset {
        name: "Dusk",
        detail: "Plum after sunset",
        palette: [
            0xece6f0, 0xada2b8, 0x7d728a, 0x1c1922, 0x25212c, 0x352f40, 0x16131b, 0x30293b,
            0xe58a98, 0x8cc7a6, 0xc3aee6, 0xdcae80, 0xa79ae0, 0x1c1330,
        ],
    },
    Preset {
        name: "Ember",
        detail: "Charcoal and warm clay",
        palette: [
            0xf0eae5, 0xb3a79e, 0x82766d, 0x1c1917, 0x25211f, 0x37302c, 0x151211, 0x332b27,
            0xe5807a, 0x93c7a0, 0xe0a48a, 0xdcb072, 0xbfa6d6, 0x2a140b,
        ],
    },
    Preset {
        name: "Fjord",
        detail: "Slate and glacier teal",
        palette: [
            0xe3eaee, 0xa0b0ba, 0x70818b, 0x171e25, 0x1f2830, 0x2e3a45, 0x11171c, 0x283540,
            0xe58c8f, 0x93c9ac, 0x8fc4c6, 0xdcb682, 0xb3a6dc, 0x0a1f20,
        ],
    },
    Preset {
        name: "Forest",
        detail: "Sage under tall trees",
        palette: [
            0xe2e9e3, 0xa0b0a5, 0x708175, 0x171c18, 0x1f2620, 0x2e3830, 0x111512, 0x28332b,
            0xe5938a, 0x9cc9a2, 0xa9c49a, 0xd9b97e, 0xb9aad2, 0x131f10,
        ],
    },
];
