use anyhow::Result;
use gpui::{App, Context, Hsla, Task, Window};
use instant::Duration;
use lsp_types::ColorInformation;
use ropey::Rope;
use std::ops::Range;

use crate::input::{EditorMode, InputBaseState, Lsp, RopeExt};

/// Maximum number of document colors accepted from a single provider response.
const MAX_DOCUMENT_COLORS: usize = 10_000;

pub trait DocumentColorProvider {
    /// Fetches document colors for the specified range.
    ///
    /// textDocument/documentColor
    ///
    /// https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_documentColor
    fn document_colors(
        &self,
        _text: &Rope,
        window: &mut Window,
        cx: &mut App,
    ) -> Task<Result<Vec<ColorInformation>>>;
}

fn document_colors_from_response(
    colors: &[ColorInformation],
) -> Option<Vec<(lsp_types::Range, Hsla)>> {
    if colors.len() > MAX_DOCUMENT_COLORS {
        return None;
    }

    let mut document_colors = colors
        .iter()
        .map(|info| {
            let color = gpui::Rgba {
                r: info.color.red,
                g: info.color.green,
                b: info.color.blue,
                a: info.color.alpha,
            }
            .into();

            (info.range, color)
        })
        .collect::<Vec<_>>();
    document_colors.sort_by_key(|(range, _)| range.start);

    Some(document_colors)
}

impl Lsp {
    /// Get document colors that intersect with the visible range (0-based row).
    ///
    /// Returns non-empty byte ranges and colors. Ranges that become empty or
    /// inverted after position conversion are ignored.
    pub(crate) fn document_colors_for_range(
        &self,
        text: &Rope,
        visible_range: &Range<usize>,
    ) -> Vec<(Range<usize>, Hsla)> {
        self.document_colors
            .iter()
            .filter_map(|(range, color)| {
                if (range.start.line as usize) > visible_range.end
                    || (range.end.line as usize) < visible_range.start
                {
                    return None;
                }

                let start = text.position_to_offset(&range.start);
                let end = text.position_to_offset(&range.end);
                if start >= end {
                    return None;
                }

                Some((start..end, *color))
            })
            .collect()
    }

    pub(crate) fn update_document_colors(
        &mut self,
        text: &Rope,
        window: &mut Window,
        cx: &mut Context<InputBaseState<EditorMode>>,
    ) {
        let Some(provider) = self.document_color_provider.as_ref() else {
            return;
        };

        let provider = provider.clone();
        let text = text.clone();
        let input_state = cx.entity();

        // debounce timer 100ms
        self._document_color_task = cx.spawn_in(window, async move |_, cx| {
            cx.background_executor()
                .timer(Duration::from_millis(100))
                .await;

            let task_result = cx
                .update(|window, cx| provider.document_colors(&text, window, cx))
                .ok();

            if let Some(task) = task_result {
                if let Ok(colors) = task.await {
                    let _ = input_state.update(cx, |input_state, cx| {
                        let Some(document_colors) = document_colors_from_response(&colors) else {
                            return;
                        };

                        if document_colors != input_state.extras.lsp.document_colors {
                            input_state.extras.lsp.document_colors = document_colors;
                            cx.notify();
                        }
                    });
                }
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lsp_types::{Position, Range as LspRange};

    #[test]
    fn test_document_colors_from_response_enforces_limit() {
        let color = ColorInformation {
            range: lsp_types::Range::new(
                lsp_types::Position::new(0, 0),
                lsp_types::Position::new(0, 1),
            ),
            color: lsp_types::Color {
                red: 1.,
                green: 0.,
                blue: 0.,
                alpha: 1.,
            },
        };
        let colors = vec![color; MAX_DOCUMENT_COLORS + 1];

        assert_eq!(
            document_colors_from_response(&colors[..MAX_DOCUMENT_COLORS])
                .unwrap()
                .len(),
            MAX_DOCUMENT_COLORS
        );
        assert!(document_colors_from_response(&colors).is_none());
    }

    #[test]
    fn test_document_colors_for_range_ignores_empty_and_inverted_ranges() {
        let text = Rope::from_str("01234567890123456789");
        let mut lsp = Lsp::default();
        lsp.document_colors.extend([
            (
                LspRange::new(Position::new(0, 10), Position::new(0, 5)),
                gpui::red(),
            ),
            (
                LspRange::new(Position::new(0, 10), Position::new(0, 10)),
                gpui::green(),
            ),
            (
                LspRange::new(Position::new(0, 5), Position::new(0, 10)),
                gpui::blue(),
            ),
        ]);

        assert_eq!(
            lsp.document_colors_for_range(&text, &(0..0)),
            vec![(5..10, gpui::blue())]
        );
    }
}
