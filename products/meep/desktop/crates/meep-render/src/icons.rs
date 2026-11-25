//! Pure saved icon data, validation and deterministic default selection.
use serde::{Deserialize, Serialize};
/// A view's icon: an emoji sticker on a patterned tile.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub struct ViewIcon {
    pub emoji: String,
    pub pattern: String,
    pub color: String,
}

/// Tile patterns, in the picker's order.
pub const ICON_PATTERNS: &[&str] = &[
    "waves", "rings", "stripes", "checks", "dots", "zigzag", "scales", "ripple", "grid",
];
/// Tile colours, in the picker's order.
pub const ICON_COLORS: &[&str] = &[
    "orange", "teal", "ink", "plum", "mustard", "moss", "brick", "slate",
];

impl ViewIcon {
    /// Refuses anything the picker could not have made.
    pub fn validate(&self) -> Result<(), &'static str> {
        if !ICON_PATTERNS.contains(&self.pattern.as_str()) {
            return Err("Unknown icon pattern.");
        }
        if !ICON_COLORS.contains(&self.color.as_str()) {
            return Err("Unknown icon colour.");
        }
        if crate::emoji::catalog().find(&self.emoji).is_none() {
            return Err("Choose an emoji from the icon picker.");
        }
        Ok(())
    }
}

use crate::emoji::catalog;
use std::{cell::RefCell, collections::HashMap};
fn hash(s: &str) -> u32 {
    s.bytes()
        .fold(2166136261u32, |h, b| (h ^ b as u32).wrapping_mul(16777619))
}

/// The icon a view shows before anyone picks one: the tile from its ID, so
/// it never changes, and the emoji from its name.
pub fn derived(id: &str, title: &str) -> ViewIcon {
    thread_local! {
        /// Suggesting searches the whole catalog, and every sidebar row asks
        /// on every frame, so each title is looked up once.
        static BY_TITLE: RefCell<HashMap<String, &'static str>> = RefCell::new(HashMap::new());
    }
    let h = hash(id);
    let emoji = BY_TITLE.with(|cache| {
        *cache
            .borrow_mut()
            .entry(title.to_owned())
            .or_insert_with(|| {
                catalog()
                    .suggest(title)
                    .first()
                    .map_or("📦", |&i| catalog().entries[i].emoji)
            })
    });
    ViewIcon {
        emoji: emoji.into(),
        pattern: ICON_PATTERNS[h as usize % ICON_PATTERNS.len()].into(),
        color: ICON_COLORS[(h >> 8) as usize % ICON_COLORS.len()].into(),
    }
}
