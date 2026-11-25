use std::ops::Range;

use gpui::{
    App, HighlightStyle, IntoElement, ParentElement, RenderOnce, SharedString, StyleRefinement,
    Styled, StyledText, Window, div, prelude::FluentBuilder, rems,
};

use gpui_base::TestTextExt as _;

use crate::{ActiveTheme, StyledExt};

const MASKED: &'static str = "•";

/// Represents the type of match for highlighting text in a label.
#[derive(Clone)]
pub enum HighlightsMatch {
    Prefix(SharedString),
    Full(SharedString),
}

impl HighlightsMatch {
    pub fn as_str(&self) -> &str {
        match self {
            Self::Prefix(s) => s.as_str(),
            Self::Full(s) => s.as_str(),
        }
    }

    #[inline]
    pub fn is_prefix(&self) -> bool {
        matches!(self, Self::Prefix(_))
    }
}

impl From<&str> for HighlightsMatch {
    fn from(value: &str) -> Self {
        Self::Full(value.to_string().into())
    }
}

impl From<String> for HighlightsMatch {
    fn from(value: String) -> Self {
        Self::Full(value.into())
    }
}

impl From<SharedString> for HighlightsMatch {
    fn from(value: SharedString) -> Self {
        Self::Full(value)
    }
}

/// A text label element with optional secondary text, masking, and highlighting capabilities.
#[derive(IntoElement)]
pub struct Label {
    style: StyleRefinement,
    label: SharedString,
    secondary: Option<SharedString>,
    masked: bool,
    highlights_text: Option<HighlightsMatch>,
}

impl Label {
    /// Create a new label with the main label.
    pub fn new(label: impl Into<SharedString>) -> Self {
        let label: SharedString = label.into();
        Self {
            style: Default::default(),
            label,
            secondary: None,
            masked: false,
            highlights_text: None,
        }
    }

    /// Set the secondary text for the label,
    /// the secondary text will be displayed after the label text with `muted` color.
    pub fn secondary(mut self, secondary: impl Into<SharedString>) -> Self {
        self.secondary = Some(secondary.into());
        self
    }

    /// Set whether to mask the label text.
    pub fn masked(mut self, masked: bool) -> Self {
        self.masked = masked;
        self
    }

    /// Set for matching text to highlight in the label.
    pub fn highlights(mut self, text: impl Into<HighlightsMatch>) -> Self {
        self.highlights_text = Some(text.into());
        self
    }

    fn full_text(&self) -> SharedString {
        match &self.secondary {
            Some(secondary) => format!("{} {}", self.label, secondary).into(),
            None => self.label.clone(),
        }
    }

    fn highlight_ranges(&self, total_length: usize) -> Vec<Range<usize>> {
        let mut ranges = Vec::new();
        let full_text = self.full_text();

        if self.secondary.is_some() {
            ranges.push(0..self.label.len());
            ranges.push(self.label.len()..total_length);
        }

        if let Some(matched) = &self.highlights_text {
            let matched_str = matched.as_str();
            if !matched_str.is_empty() {
                let search_lower = matched_str.to_lowercase();
                let full_text_lower = full_text.to_lowercase();

                if matched.is_prefix() {
                    // For prefix matching, only check if the text starts with the search term
                    if full_text_lower.starts_with(&search_lower) {
                        ranges.push(0..matched_str.len());
                    }
                } else {
                    // For full matching, find all occurrences
                    let mut search_start = 0;
                    while let Some(pos) = full_text_lower[search_start..].find(&search_lower) {
                        let match_start = search_start + pos;
                        let match_end = match_start + matched_str.len();

                        if match_end <= full_text.len() {
                            ranges.push(match_start..match_end);
                        }

                        search_start = match_start + 1;
                        while !full_text.is_char_boundary(search_start)
                            && search_start < full_text.len()
                        {
                            search_start += 1;
                        }

                        if search_start >= full_text.len() {
                            break;
                        }
                    }
                }
            }
        }

        ranges
    }

    fn measure_highlights(
        &self,
        length: usize,
        cx: &mut App,
    ) -> Option<Vec<(Range<usize>, HighlightStyle)>> {
        if self.masked {
            return None;
        }

        let ranges = self.highlight_ranges(length);
        if ranges.is_empty() {
            return None;
        }

        let mut highlights = Vec::new();
        let mut highlight_ranges_added = 0;

        if self.secondary.is_some() {
            highlights.push((ranges[0].clone(), HighlightStyle::default()));
            highlights.push((
                ranges[1].clone(),
                HighlightStyle {
                    color: Some(cx.theme().muted_foreground),
                    ..Default::default()
                },
            ));
            highlight_ranges_added = 2;
        }

        for range in ranges.iter().skip(highlight_ranges_added) {
            highlights.push((
                range.clone(),
                HighlightStyle {
                    color: Some(cx.theme().blue),
                    ..Default::default()
                },
            ));
        }

        Some(gpui::combine_highlights(vec![], highlights).collect())
    }
}

impl Styled for Label {
    fn style(&mut self) -> &mut gpui::StyleRefinement {
        &mut self.style
    }
}

impl RenderOnce for Label {
    fn render(self, _: &mut Window, cx: &mut App) -> impl IntoElement {
        let mut text = self.full_text();
        let chars_count = text.chars().count();

        if self.masked {
            text = SharedString::from(MASKED.repeat(chars_count))
        };

        let highlights = self.measure_highlights(text.len(), cx);

        div()
            .line_height(rems(1.25))
            .text_color(cx.theme().foreground)
            .refine_style(&self.style)
            .child(
                StyledText::new(&text).when_some(highlights, |this, hl| this.with_highlights(hl)),
            )
            .test_text(text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct MaskedLabels;

    impl gpui::Render for MaskedLabels {
        fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
            div()
                .child(Label::new("Hello").secondary("World").masked(true))
                .child(Label::new("Hello").highlights("ell").masked(true))
                .child(
                    Label::new("é🙂")
                        .secondary("世界")
                        .highlights("🙂 世")
                        .masked(true),
                )
        }
    }

    #[gpui::test]
    fn masked_secondary_text_and_highlights_render(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);
        cx.update(|cx| {
            let label = Label::new("é🙂")
                .secondary("世界")
                .highlights("🙂 世")
                .masked(true);
            assert!(
                label
                    .measure_highlights(label.full_text().len(), cx)
                    .is_none()
            );
        });
        let (_, cx) = cx.add_window_view(|_, _| MaskedLabels);
        cx.update(|window, cx| window.draw(cx).clear(cx));
    }

    #[cfg(feature = "test-support")]
    #[gpui::test]
    fn records_displayed_text_under_its_identified_parent(cx: &mut gpui::TestAppContext) {
        use gpui::InteractiveElement as _;

        struct Labels;
        impl gpui::Render for Labels {
            fn render(&mut self, _: &mut Window, _: &mut gpui::Context<Self>) -> impl IntoElement {
                div()
                    .id("box")
                    .child(Label::new("Hello"))
                    .child(Label::new("secret").masked(true))
            }
        }
        cx.update(crate::init);
        let (_, cx) = cx.add_window_view(|_, _| Labels);
        // Root starts each frame; this window has none.
        cx.update(|window, cx| {
            gpui_base::test_support::begin_frame(window);
            window.draw(cx).clear(cx)
        });
        cx.update(|window, _| {
            let texts: Vec<_> = gpui_base::test_support::texts(window)
                .iter()
                .map(|text| {
                    assert!(text.path().contains(&"box".into()), "{:?}", text.path());
                    text.text().to_owned()
                })
                .collect();
            assert_eq!(texts, ["Hello", "••••••"]);
        });
    }

    #[test]
    fn test_highlight_ranges() {
        // Basic functionality

        // No highlights
        let label = Label::new("Hello World");
        let result = label.highlight_ranges("Hello World".len());
        assert_eq!(result, Vec::<Range<usize>>::new());

        // Secondary text ranges only
        let label = Label::new("Hello").secondary("World");
        let total_length = "Hello World".len();
        let result = label.highlight_ranges(total_length);
        assert_eq!(result.len(), 2);
        assert_eq!(result[0], 0..5); // "Hello"
        assert_eq!(result[1], 5..11); // " World"

        // Text highlighting

        // Single match with case insensitive
        let label = Label::new("Hello World").highlights("WORLD");
        let result = label.highlight_ranges("Hello World".len());
        assert_eq!(result.len(), 1);
        assert_eq!(result[0], 6..11); // "World"

        // Multiple matches
        let label = Label::new("Hello Hello Hello").highlights("Hello");
        let result = label.highlight_ranges("Hello Hello Hello".len());
        assert_eq!(result.len(), 3);
        assert_eq!(result[0], 0..5); // First "Hello"
        assert_eq!(result[1], 6..11); // Second "Hello"
        assert_eq!(result[2], 12..17); // Third "Hello"

        // No match and empty search
        let label = Label::new("Hello World").highlights("xyz");
        let result = label.highlight_ranges("Hello World".len());
        assert_eq!(result, Vec::<Range<usize>>::new());

        let label = Label::new("Hello World").highlights("");
        let result = label.highlight_ranges("Hello World".len());
        assert_eq!(result, Vec::<Range<usize>>::new());

        // Combined functionality

        // Secondary + highlights in main text
        let label = Label::new("Hello").secondary("World").highlights("llo");
        let total_length = "Hello World".len();
        let result = label.highlight_ranges(total_length);
        assert_eq!(result.len(), 3);
        assert_eq!(result[0], 0..5); // Main text range
        assert_eq!(result[1], 5..11); // Secondary text range
        assert_eq!(result[2], 2..5); // "llo" in main text

        // Highlight in secondary text
        let label = Label::new("Hello").secondary("World").highlights("World");
        let total_length = "Hello World".len();
        let result = label.highlight_ranges(total_length);
        assert_eq!(result.len(), 3);
        assert_eq!(result[0], 0..5); // Main text range
        assert_eq!(result[1], 5..11); // Secondary text range
        assert_eq!(result[2], 6..11); // "World" in secondary text

        // Cross-boundary highlight
        let label = Label::new("Hello").secondary("World").highlights("o W");
        let total_length = "Hello World".len();
        let result = label.highlight_ranges(total_length);
        assert_eq!(result.len(), 3);
        assert_eq!(result[0], 0..5); // Main text range
        assert_eq!(result[1], 5..11); // Secondary text range
        assert_eq!(result[2], 4..7); // "o W" across boundary

        // Edge cases

        // Overlapping matches
        let label = Label::new("aaaa").highlights("aa");
        let result = label.highlight_ranges("aaaa".len());
        assert!(result.len() >= 2);
        assert_eq!(result[0], 0..2); // First "aa"
        assert_eq!(result[1], 1..3); // Overlapping "aa"

        // Unicode text
        let label = Label::new("你好世界，Hello World").highlights("世界");
        let result = label.highlight_ranges("你好世界，Hello World".len());
        assert_eq!(result.len(), 1);
        let text = "你好世界，Hello World";
        let start = text.find("世界").unwrap();
        let end = start + "世界".len();
        assert_eq!(result[0], start..end);
    }

    #[test]
    fn test_highlight_ranges_prefix() {
        // Test prefix match - should only match the first occurrence
        let label = Label::new("aaaa").highlights(HighlightsMatch::Prefix("aa".into()));
        let result = label.highlight_ranges("aaaa".len());
        assert_eq!(result.len(), 1);
        assert_eq!(result[0], 0..2); // Only first "aa"

        // Test prefix vs full match behavior
        let label_full =
            Label::new("Hello Hello").highlights(HighlightsMatch::Full("Hello".into()));
        let result_full = label_full.highlight_ranges("Hello Hello".len());
        assert_eq!(result_full.len(), 2); // Both "Hello" matches

        let label_prefix =
            Label::new("Hello Hello").highlights(HighlightsMatch::Prefix("Hello".into()));
        let result_prefix = label_prefix.highlight_ranges("Hello Hello".len());
        assert_eq!(result_prefix.len(), 1); // Only first "Hello"
        assert_eq!(result_prefix[0], 0..5);

        // Test prefix with case insensitive matching
        let label =
            Label::new("Hello hello HELLO").highlights(HighlightsMatch::Prefix("hello".into()));
        let result = label.highlight_ranges("Hello hello HELLO".len());
        assert_eq!(result.len(), 1);
        assert_eq!(result[0], 0..5); // First "Hello" (case insensitive)

        // Test prefix with no match
        let label = Label::new("Hello World").highlights(HighlightsMatch::Prefix("xyz".into()));
        let result = label.highlight_ranges("Hello World".len());
        assert_eq!(result.len(), 0);

        // Test prefix with empty string
        let label = Label::new("Hello World").highlights(HighlightsMatch::Prefix("".into()));
        let result = label.highlight_ranges("Hello World".len());
        assert_eq!(result.len(), 0);

        // Test prefix with secondary text - match in main text
        let label = Label::new("Hello")
            .secondary("Hello World")
            .highlights(HighlightsMatch::Prefix("Hello".into()));
        let total_length = "Hello Hello World".len();
        let result = label.highlight_ranges(total_length);
        assert_eq!(result.len(), 3); // 2 for secondary + 1 for prefix match
        assert_eq!(result[0], 0..5); // Main text range
        assert_eq!(result[1], 5..17); // Secondary text range
        assert_eq!(result[2], 0..5); // First "Hello" prefix match in main text

        // Test prefix with secondary text - match spans boundary (now no match since "abc" is not at start of full text)
        let label = Label::new("abc")
            .secondary("def abc def")
            .highlights(HighlightsMatch::Prefix("abc".into()));
        let total_length = "abc def abc def".len();
        let result = label.highlight_ranges(total_length);
        assert_eq!(result.len(), 3); // 2 for secondary + 1 for prefix match
        assert_eq!(result[0], 0..3); // Main text range
        assert_eq!(result[1], 3..15); // Secondary text range
        assert_eq!(result[2], 0..3); // "abc" matches at start of full text

        // Test prefix with Unicode characters
        let label = Label::new("你好世界你好").highlights(HighlightsMatch::Prefix("你好".into()));
        let result = label.highlight_ranges("你好世界你好".len());
        assert_eq!(result.len(), 1);
        assert_eq!(result[0], 0..6); // First "你好" (6 bytes in UTF-8)

        // Test prefix with overlapping pattern
        let label = Label::new("abababab").highlights(HighlightsMatch::Prefix("abab".into()));
        let result = label.highlight_ranges("abababab".len());
        assert_eq!(result.len(), 1);
        assert_eq!(result[0], 0..4); // First "abab" only

        // Test prefix match at different positions (now no match since "Hello" is not at start)
        let label =
            Label::new("xyz Hello abc Hello").highlights(HighlightsMatch::Prefix("Hello".into()));
        let result = label.highlight_ranges("xyz Hello abc Hello".len());
        assert_eq!(result.len(), 0); // No match since "Hello" is not at the beginning

        // Test is_prefix method
        let prefix_match = HighlightsMatch::Prefix("test".into());
        let full_match = HighlightsMatch::Full("test".into());
        assert!(prefix_match.is_prefix());
        assert!(!full_match.is_prefix());

        // Test as_str method for prefix
        let prefix_match = HighlightsMatch::Prefix("test".into());
        assert_eq!(prefix_match.as_str(), "test");
    }
}
