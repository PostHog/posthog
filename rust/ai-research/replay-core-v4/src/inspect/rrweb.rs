//! The rrweb numbers the inspector routes on, as `rrweb-types.ts` defines them.

pub const FULL_SNAPSHOT: u8 = 2;
pub const INCREMENTAL_SNAPSHOT: u8 = 3;
pub const META: u8 = 4;
pub const CUSTOM: u8 = 5;
pub const PLUGIN: u8 = 6;

pub const MUTATION: u8 = 0;
pub const MOUSE_MOVE: u8 = 1;
pub const MOUSE_INTERACTION: u8 = 2;
pub const SCROLL: u8 = 3;
pub const VIEWPORT_RESIZE: u8 = 4;
pub const INPUT: u8 = 5;
pub const TOUCH_MOVE: u8 = 6;
pub const MEDIA_INTERACTION: u8 = 7;
pub const STYLE_SHEET_RULE: u8 = 8;
pub const DRAG: u8 = 12;
pub const STYLE_DECLARATION: u8 = 13;
pub const SELECTION: u8 = 14;
pub const ADOPTED_STYLE_SHEET: u8 = 15;

pub const CLICK: u8 = 2;
pub const CONTEXT_MENU: u8 = 3;
pub const DOUBLE_CLICK: u8 = 4;
pub const TOUCH_START: u8 = 7;
pub const TOUCH_END: u8 = 9;

/// Sources that count as user activity, as in `segmentation.ts`.
pub fn is_active_source(source: u8) -> bool {
    matches!(
        source,
        MOUSE_MOVE
            | MOUSE_INTERACTION
            | SCROLL
            | VIEWPORT_RESIZE
            | INPUT
            | TOUCH_MOVE
            | MEDIA_INTERACTION
            | DRAG
    )
}

/// Mouse interactions that count as clicks, as in `rrweb-types.ts`.
pub fn is_click(interaction: u8) -> bool {
    matches!(interaction, CLICK | DOUBLE_CLICK | TOUCH_END | CONTEXT_MENU)
}
