use std::{cell::RefCell, rc::Rc};

use gpui::{AppContext, Empty, ListOffset, TestAppContext, px, size};

use super::{
    DiffEvent, DiffFile, DiffLinePosition, DiffLineRange, DiffMode, DiffSide, DiffState,
    document::fixture, state::DisplayRow,
};

fn document(original: &str, modified: &str) -> DiffFile {
    fixture::modified("review.txt", original, modified)
}

fn context_document() -> DiffFile {
    let original = (1..=30)
        .map(|line| format!("line {line}\n"))
        .collect::<String>();
    let modified = original.replace("line 15\n", "changed 15\n");
    document(&original, &modified)
}

#[gpui::test]
fn unified_changes_keep_deletions_before_additions_and_source_selection(cx: &mut TestAppContext) {
    let state = cx.new(|cx| {
        DiffState::new(
            [document(
                "head\nold one\nold two\ntail\n",
                "head\nnew one\nnew two\nnew three\ntail\n",
            )],
            cx,
        )
    });
    state.update(cx, |state, cx| {
        assert_eq!(state.mode(), DiffMode::Unified);
        state.set_mode(DiffMode::Split, cx);
        state.set_context_lines(None, cx);
        state.set_selected_lines(
            Some(DiffLineRange::new("review.txt", DiffSide::Original, 2, 3)),
            cx,
        );
        state.list().scroll_to(ListOffset {
            item_ix: 2,
            offset_in_item: px(0.),
        });
        state.set_mode(DiffMode::Unified, cx);
        assert_eq!(state.list().logical_scroll_top().item_ix, 4);
        let changes = state
            .rows()
            .iter()
            .filter_map(|row| match row {
                DisplayRow::Code {
                    original,
                    modified,
                    changed: true,
                    ..
                } => Some((*original, *modified)),
                _ => None,
            })
            .collect::<Vec<_>>();
        assert_eq!(
            changes,
            [
                (Some(1), None),
                (Some(2), None),
                (None, Some(1)),
                (None, Some(2)),
                (None, Some(3))
            ]
        );
        assert_eq!(
            state.selected_lines(),
            Some(DiffLineRange::new("review.txt", DiffSide::Original, 2, 3))
        );
        assert_eq!(state.selected_text(cx), "old one\nold two\n");

        state.set_mode(DiffMode::Split, cx);
        assert_eq!(state.list().logical_scroll_top().item_ix, 2);
        let changes = state
            .rows()
            .iter()
            .filter_map(|row| match row {
                DisplayRow::Code {
                    original,
                    modified,
                    changed: true,
                    ..
                } => Some((*original, *modified)),
                _ => None,
            })
            .collect::<Vec<_>>();
        assert_eq!(
            changes,
            [(Some(1), Some(1)), (Some(2), Some(2)), (None, Some(3))]
        );
        assert_eq!(state.selected_text(cx), "old one\nold two\n");
    });
}

#[gpui::test]
fn context_disclosures_reveal_source_ranges_without_retargeting_selection(cx: &mut TestAppContext) {
    let state = cx.new(|cx| DiffState::new([context_document()], cx));
    state.update(cx, |state, cx| {
        state.set_mode(DiffMode::Split, cx);
        state.set_context_lines(Some(1), cx);
        let folds = state
            .rows()
            .iter()
            .filter_map(|row| match row {
                DisplayRow::Fold { pairs, .. } => Some(pairs.clone()),
                _ => None,
            })
            .collect::<Vec<_>>();
        assert_eq!(folds, [0..13, 16..30]);

        state.set_selected_lines(
            Some(DiffLineRange::new("review.txt", DiffSide::Modified, 14, 16)),
            cx,
        );
        state.list().scroll_to(ListOffset {
            item_ix: 3,
            offset_in_item: px(0.),
        });
        state.expand_fold(0, folds[0].clone(), super::state::FoldExpansion::All, cx);
        assert_eq!(state.list().logical_scroll_top().item_ix, 15);
        assert!(matches!(
            state.rows().get(1),
            Some(DisplayRow::Code {
                original: Some(0),
                modified: Some(0),
                changed: false,
                ..
            })
        ));
        assert_eq!(
            state
                .rows()
                .iter()
                .filter(|row| matches!(row, DisplayRow::Fold { .. }))
                .count(),
            1
        );
        assert_eq!(state.selected_text(cx), "line 14\nchanged 15\nline 16\n");

        state.scroll_to_line(
            DiffLinePosition::new("review.txt", DiffSide::Original, 30),
            cx,
        );
        assert_eq!(state.list().logical_scroll_top().item_ix, 30);
        assert!(
            !state
                .rows()
                .iter()
                .any(|row| matches!(row, DisplayRow::Fold { .. }))
        );
        state.collapse_unchanged(cx);
        assert_eq!(state.context_lines(), Some(1));
        assert_eq!(
            state.selected_lines(),
            Some(DiffLineRange::new("review.txt", DiffSide::Modified, 14, 16))
        );
        state.expand_unchanged(cx);
        assert_eq!(state.rows().len(), 31);
        assert!(
            !state
                .rows()
                .iter()
                .any(|row| matches!(row, DisplayRow::Fold { .. }))
        );

        // Rebuilt source maps must distinguish deletion and addition rows in
        // Unified, then point both source sides back to the paired Split row.
        state.set_mode(DiffMode::Unified, cx);
        for side in [DiffSide::Original, DiffSide::Modified] {
            state.scroll_to_line(DiffLinePosition::new("review.txt", side, 15), cx);
            let row = &state.rows()[state.list().logical_scroll_top().item_ix];
            assert!(match (side, row) {
                (
                    DiffSide::Original,
                    DisplayRow::Code {
                        original: Some(14),
                        modified: None,
                        ..
                    },
                ) => true,
                (
                    DiffSide::Modified,
                    DisplayRow::Code {
                        original: None,
                        modified: Some(14),
                        ..
                    },
                ) => true,
                _ => false,
            });
        }
        state.set_mode(DiffMode::Split, cx);
        for side in [DiffSide::Original, DiffSide::Modified] {
            state.scroll_to_line(DiffLinePosition::new("review.txt", side, 15), cx);
            assert_eq!(state.list().logical_scroll_top().item_ix, 15);
        }

        // An unavailable source line must not alter the current disclosure state.
        let count = state.rows().len();
        state.scroll_to_line(
            DiffLinePosition::new("review.txt", DiffSide::Original, usize::MAX),
            cx,
        );
        assert_eq!(state.rows().len(), count);
        state.set_context_lines(Some(0), cx);
        assert_eq!(state.rows().len(), 4);
        assert_eq!(state.selected_text(cx), "line 14\nchanged 15\nline 16\n");
    });
}

#[gpui::test]
fn source_selection_clamps_ranges_and_preserves_original_bytes(cx: &mut TestAppContext) {
    let state = cx.new(|cx| {
        DiffState::new(
            [document("\t旧值  \r\n\r\nlast", "\t新值  \r\n\r\nlast")],
            cx,
        )
    });
    state.update(cx, |state, cx| {
        state.set_selected_lines(
            Some(DiffLineRange::new(
                "review.txt",
                DiffSide::Original,
                usize::MAX,
                0,
            )),
            cx,
        );
        assert_eq!(
            state.selected_lines(),
            Some(DiffLineRange::new("review.txt", DiffSide::Original, 1, 3))
        );
        assert_eq!(state.selected_text(cx), "\t旧值  \r\n\r\nlast");
        state.set_selected_lines(
            Some(DiffLineRange::new(
                "review.txt",
                DiffSide::Modified,
                2,
                usize::MAX,
            )),
            cx,
        );
        assert_eq!(state.selected_text(cx), "\r\nlast");
        state.set_selected_lines(
            Some(DiffLineRange::new("review.txt", DiffSide::Original, 20, 30)),
            cx,
        );
        assert_eq!(state.selected_lines(), None);
        assert_eq!(state.selected_text(cx), "");
        state.set_selected_lines(None, cx);
        assert_eq!(state.selected_text(cx), "");
    });

    let deleted =
        cx.new(|cx| DiffState::new([fixture::document(Some(("deleted", "one\n")), None)], cx));
    deleted.update(cx, |state, cx| {
        state.set_selected_lines(
            Some(DiffLineRange::new("review.txt", DiffSide::Modified, 1, 2)),
            cx,
        );
        assert!(state.selected_lines().is_none());
        assert_eq!(state.selected_text(cx), "");
    });
    let empty = cx.new(|cx| DiffState::new([document("", "")], cx));
    empty.update(cx, |state, cx| {
        state.set_selected_lines(
            Some(DiffLineRange::new("review.txt", DiffSide::Original, 1, 1)),
            cx,
        );
        assert!(state.selected_lines().is_none());
        assert_eq!(state.selected_text(cx), "");
    });
}

#[gpui::test]
fn change_navigation_wraps_groups_and_unchanged_documents_stay_in_place(cx: &mut TestAppContext) {
    let state = cx.new(|cx| {
        DiffState::new(
            [document(
                "head\nold first\nmiddle\nold last\ntail\n",
                "head\nnew first\nmiddle\nnew last\ntail\n",
            )],
            cx,
        )
    });
    state.update(cx, |state, cx| {
        state.set_mode(DiffMode::Split, cx);
        state.set_context_lines(None, cx);
        state.list().scroll_to(ListOffset::default());
        state.next_change(cx);
        assert_eq!(state.list().logical_scroll_top().item_ix, 2);
        state.next_change(cx);
        assert_eq!(state.list().logical_scroll_top().item_ix, 4);
        state.next_change(cx);
        assert_eq!(state.list().logical_scroll_top().item_ix, 2);
        state.previous_change(cx);
        assert_eq!(state.list().logical_scroll_top().item_ix, 4);
        state.previous_change(cx);
        assert_eq!(state.list().logical_scroll_top().item_ix, 2);
    });

    let same =
        cx.new(|cx| DiffState::new([document("one\ntwo\nthree\n", "one\ntwo\nthree\n")], cx));
    same.update(cx, |state, cx| {
        state.set_context_lines(None, cx);
        state.list().scroll_to(ListOffset {
            item_ix: 1,
            offset_in_item: px(0.),
        });
        state.next_change(cx);
        state.previous_change(cx);
        assert_eq!(state.list().logical_scroll_top().item_ix, 1);
    });
}

#[gpui::test]
fn controlled_selection_stays_silent_and_coherent_changes_notify(cx: &mut TestAppContext) {
    let state = cx.new(|cx| DiffState::new([document("old\n", "new\n")], cx));
    let events = Rc::new(RefCell::new(Vec::new()));
    let notifications = Rc::new(RefCell::new(0));
    let _events = cx.update(|cx| {
        let events = events.clone();
        cx.subscribe(&state, move |_, event: &DiffEvent, _| {
            if let DiffEvent::SelectionChanged(range) = event {
                events.borrow_mut().push(range.clone());
            }
        })
    });
    let _notifications = cx.update(|cx| {
        let notifications = notifications.clone();
        cx.observe(&state, move |_, _| *notifications.borrow_mut() += 1)
    });
    let range = DiffLineRange::new("review.txt", DiffSide::Modified, 1, 1);
    state.update(cx, |state, cx| {
        state.set_selected_lines(Some(range.clone()), cx)
    });
    assert!(events.borrow().is_empty());
    assert_eq!(*notifications.borrow(), 1);
    state.update(cx, |state, cx| state.set_selected_lines(Some(range), cx));
    assert_eq!(*notifications.borrow(), 1);
    state.update(cx, |state, cx| state.set_mode(DiffMode::Split, cx));
    assert!(events.borrow().is_empty());
    assert_eq!(*notifications.borrow(), 2);
    state.update(cx, |state, cx| state.set_mode(DiffMode::Split, cx));
    assert_eq!(*notifications.borrow(), 2);
    state.update(cx, |state, cx| state.set_selected_lines(None, cx));
    assert!(events.borrow().is_empty());
    assert_eq!(*notifications.borrow(), 3);
}

#[gpui::test]
fn user_line_selection_extends_on_one_side_and_replacement_resets_silently(
    cx: &mut TestAppContext,
) {
    // This fixture needs a Window for focus and selection cleanup, but never
    // renders Component content. Rendered pointer/key paths live in Kit tests.
    let window = cx.open_window(size(px(640.), px(480.)), |_, _| Empty);
    let state = cx.new(|cx| {
        DiffState::new(
            [document(
                "old one\r\nold two\r\nold three",
                "new one\r\nnew two\r\nnew three",
            )],
            cx,
        )
    });
    let events = Rc::new(RefCell::new(Vec::new()));
    let _subscription = cx.update(|cx| {
        let events = events.clone();
        cx.subscribe(&state, move |_, event: &DiffEvent, _| {
            if let DiffEvent::SelectionChanged(range) = event {
                events.borrow_mut().push(range.clone());
            }
        })
    });
    cx.update_window(window.into(), |_, window, cx| {
        state.update(cx, |state, cx| {
            state.click_line(
                DiffLinePosition::new("review.txt", DiffSide::Original, 2),
                false,
                window,
                cx,
            );
            assert!(state.selection().has_local_selection(cx));
            // Base clears local participation synchronously, before its queued
            // notification reaches DiffState. Copy must stop immediately while
            // the retained gutter anchor still supports a subsequent extension.
            state.selection().set_local_selection(false, cx);
            assert_eq!(state.selected_text(cx), "");
            state.keyboard_select(1, true, window, cx);
            assert_eq!(
                state.selected_lines(),
                Some(DiffLineRange::new("review.txt", DiffSide::Original, 2, 3))
            );
            assert_eq!(state.selected_text(cx), "old two\r\nold three");
            state.keyboard_select(-1, true, window, cx);
            assert_eq!(
                state.selected_lines(),
                Some(DiffLineRange::new("review.txt", DiffSide::Original, 2, 2))
            );
            // Unified rows follow patch order, so Shift-click crosses sides.
            state.click_line(
                DiffLinePosition::new("review.txt", DiffSide::Modified, 3),
                true,
                window,
                cx,
            );
            assert_eq!(
                state.selected_lines(),
                Some(
                    DiffLineRange::new("review.txt", DiffSide::Original, 2, 3)
                        .with_end_side(DiffSide::Modified)
                )
            );
            assert_eq!(
                state.selected_text(cx),
                "old two\r\nold three\nnew one\r\nnew two\r\nnew three"
            );
            // Split columns are separate; changing side starts a new selection.
            state.set_mode(DiffMode::Split, cx);
            state.click_line(
                DiffLinePosition::new("review.txt", DiffSide::Original, 1),
                false,
                window,
                cx,
            );
            state.click_line(
                DiffLinePosition::new("review.txt", DiffSide::Modified, 3),
                true,
                window,
                cx,
            );
            assert_eq!(
                state.selected_lines(),
                Some(DiffLineRange::new("review.txt", DiffSide::Modified, 3, 3))
            );
            state.select_all(window, cx);
            assert_eq!(state.selected_text(cx), "new one\r\nnew two\r\nnew three");
            state.set_files(
                [fixture::document(Some(("replacement", "one\ntwo\n")), None)],
                cx,
            );
            assert!(state.selected_lines().is_none());
            assert!(!state.selection().has_local_selection(cx));
            assert_eq!(state.selected_text(cx), "");
            assert_eq!(state.list().logical_scroll_top().item_ix, 0);
            assert_eq!(
                state.files()[0].original_path().unwrap().as_str(),
                "replacement"
            );
        });
    })
    .unwrap();
    assert_eq!(
        events.borrow().as_slice(),
        &[
            Some(DiffLineRange::new("review.txt", DiffSide::Original, 2, 2)),
            Some(DiffLineRange::new("review.txt", DiffSide::Original, 2, 3)),
            Some(DiffLineRange::new("review.txt", DiffSide::Original, 2, 2)),
            Some(
                DiffLineRange::new("review.txt", DiffSide::Original, 2, 3)
                    .with_end_side(DiffSide::Modified)
            ),
            Some(DiffLineRange::new("review.txt", DiffSide::Original, 1, 1)),
            Some(DiffLineRange::new("review.txt", DiffSide::Modified, 3, 3)),
            Some(DiffLineRange::new("review.txt", DiffSide::Modified, 1, 3)),
        ]
    );
    cx.update_window(window.into(), |_, window, cx| {
        state.update(cx, |state, cx| {
            state.keyboard_select(1, true, window, cx);
            assert_eq!(
                state.selected_lines(),
                Some(DiffLineRange::new("replacement", DiffSide::Original, 1, 1))
            );
            state.keyboard_select(-1, true, window, cx);
            assert_eq!(
                state.selected_lines(),
                Some(DiffLineRange::new("replacement", DiffSide::Original, 1, 1))
            );
        });
    })
    .unwrap();
    assert_eq!(events.borrow().len(), 8);
}

#[gpui::test]
fn patch_navigation_and_selection_use_supplied_source_coordinates(cx: &mut TestAppContext) {
    let document = DiffFile::parse(
        "--- a/review.txt\n+++ b/review.txt\n@@ -100,2 +100,2 @@ first\n context 100\n-old 101\n+new 101\n@@ -200,2 +200,2 @@ second\n context 200\n-old 201\n+new 201\n",
    )
    .unwrap()
    .remove(0);
    let state = cx.new(|cx| DiffState::new([document], cx));
    let window = cx.open_window(size(px(640.), px(480.)), |_, _| Empty);
    cx.update_window(window.into(), |_, window, cx| {
        state.update(cx, |state, cx| {
            assert_eq!(
                state
                    .rows()
                    .iter()
                    .filter(|row| matches!(row, DisplayRow::Hunk { .. }))
                    .count(),
                2
            );
            assert!(
                !state
                    .rows()
                    .iter()
                    .any(|row| matches!(row, DisplayRow::Fold { .. }))
            );
            state.keyboard_select(1, false, window, cx);
            assert_eq!(state.selected_lines().unwrap().start(), 100);
            state.keyboard_select(1, true, window, cx);
            state.keyboard_select(1, true, window, cx);
            assert_eq!(
                state.selected_lines(),
                Some(DiffLineRange::new(
                    "review.txt",
                    DiffSide::Modified,
                    100,
                    200
                ))
            );
            assert_eq!(
                state.selected_text(cx),
                "context 100\nnew 101\ncontext 200\n"
            );
            state.set_selected_lines(
                Some(DiffLineRange::new(
                    "review.txt",
                    DiffSide::Modified,
                    105,
                    150,
                )),
                cx,
            );
            assert_eq!(state.selected_lines(), None);
            let top = state.list().logical_scroll_top();
            state.scroll_to_line(
                DiffLinePosition::new("review.txt", DiffSide::Modified, 150),
                cx,
            );
            assert_eq!(state.list().logical_scroll_top().item_ix, top.item_ix);
            assert_eq!(
                state.list().logical_scroll_top().offset_in_item,
                top.offset_in_item
            );
        });
    })
    .unwrap();
}

#[gpui::test]
fn setting_or_clearing_a_syntax_highlighter_prepares_the_files_again(cx: &mut TestAppContext) {
    use gpui::{FontStyle, FontWeight, HighlightStyle};
    use gpui_base::input::HighlightStyleResolver;
    use std::ops::Range;

    /// Paints GPUI Kit's `keyword` captures italic and nothing else.
    struct KeywordTheme;
    impl HighlightStyleResolver for KeywordTheme {
        fn style(&self, name: &str) -> Option<HighlightStyle> {
            (name == "keyword").then(|| HighlightStyle {
                font_style: Some(FontStyle::Italic),
                ..Default::default()
            })
        }
    }
    let first_word = |weight| {
        let style = HighlightStyle {
            font_weight: Some(weight),
            ..Default::default()
        };
        move |_: &str, text: &str| -> Vec<(Range<usize>, HighlightStyle)> {
            vec![(0..text.find(' ').unwrap_or(text.len()), style)]
        }
    };
    let file = document("let a = 1;\n", "let a = 2;\n").with_language("rust");
    let state = cx.new(|cx| {
        DiffState::new([file.clone()], cx).with_syntax_highlighter(first_word(FontWeight::BOLD))
    });
    let styles = |cx: &mut TestAppContext| {
        state.update(cx, |state, cx| {
            state.ensure_presentation(cx);
        });
        cx.run_until_parked();
        state.read_with(cx, |state, _| {
            let presentation = state.presentations()[0]
                .as_ref()
                .expect("the file is prepared");
            let line = &file.lines(DiffSide::Modified)[0];
            presentation
                .syntax_highlights(line, DiffSide::Modified, 0, &KeywordTheme)
                .into_iter()
                .map(|(_, style)| style)
                .collect::<Vec<_>>()
        })
    };
    let weights = |styles: &[HighlightStyle]| {
        styles
            .iter()
            .filter_map(|style| style.font_weight)
            .collect::<Vec<_>>()
    };
    assert_eq!(weights(&styles(cx)), [FontWeight::BOLD]);

    state.update(cx, |state, cx| {
        state.set_syntax_highlighter(first_word(FontWeight::LIGHT), cx);
    });
    assert_eq!(weights(&styles(cx)), [FontWeight::LIGHT]);

    state.update(cx, |state, cx| state.clear_syntax_highlighter(cx));
    let cleared = styles(cx);
    assert!(
        weights(&cleared).is_empty(),
        "the application's styles are gone"
    );
    // With the grammar, GPUI Kit highlights `let` again.
    #[cfg(feature = "tree-sitter-rust")]
    assert!(
        cleared
            .iter()
            .any(|style| style.font_style == Some(FontStyle::Italic))
    );
}
