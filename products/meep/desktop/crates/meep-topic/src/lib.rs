#![doc = include_str!("../README.md")]
#![deny(missing_docs)]

mod ids;
mod model;
mod state;

pub use ids::*;
pub use model::*;
pub use state::*;

/// A one-line title from free text: its first non-empty line without markdown
/// markers, cut at a word near 100 characters.
pub fn title_line(text: &str) -> String {
    let line = text
        .lines()
        .map(str::trim)
        .find(|l| !l.is_empty())
        .unwrap_or_default()
        .trim_start_matches(['#', '-', '*', '>', ' '])
        .replace("**", "")
        .replace('`', "");
    const MAX: usize = 100;
    if line.chars().count() <= MAX {
        return line;
    }
    let cut: String = line.chars().take(MAX).collect();
    let cut = cut.rsplit_once(' ').map_or(cut.as_str(), |(head, _)| head);
    format!("{}…", cut.trim_end_matches([',', ';', ':', '.', ' ']))
}

#[cfg(feature = "fixtures")]
pub mod fixtures;

#[cfg(test)]
mod tests;
