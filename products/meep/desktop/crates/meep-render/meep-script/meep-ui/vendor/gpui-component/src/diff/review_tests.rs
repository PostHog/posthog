use std::{cell::RefCell, rc::Rc};

use gpui::{AppContext, Empty, ListOffset, TestAppContext, px, size};

use super::{
    DiffEvent, DiffFile, DiffFileStatus, DiffLinePosition, DiffLineRange, DiffMode, DiffSide,
    DiffState,
    state::{DisplayRow, FoldExpansion},
};

const PATCH: &str = "diff --git a/first.txt b/first.txt\n--- a/first.txt\n+++ b/first.txt\n@@ -1,3 +1,3 @@\n one\n-two\n+TWO\n three\ndiff --git a/second.txt b/second.txt\n--- a/second.txt\n+++ b/second.txt\n@@ -10 +10 @@\n-ten\n+TEN\n";

fn record_events(
    cx: &mut TestAppContext,
    state: &gpui::Entity<DiffState>,
) -> (Rc<RefCell<Vec<DiffEvent>>>, gpui::Subscription) {
    let events = Rc::new(RefCell::new(Vec::new()));
    let subscription = cx.update(|cx| {
        let events = events.clone();
        cx.subscribe(state, move |_, event: &DiffEvent, _| {
            events.borrow_mut().push(event.clone())
        })
    });
    (events, subscription)
}

fn code_rows(state: &DiffState, file: usize) -> usize {
    state
        .rows()
        .iter()
        .filter(|row| matches!(row, DisplayRow::Code { file: f, .. } if *f == file))
        .count()
}

#[gpui::test]
fn collapsed_files_keep_their_header_and_survive_replacement(cx: &mut TestAppContext) {
    let state = cx.new(|cx| DiffState::new(DiffFile::parse(PATCH).unwrap(), cx));
    let (events, _subscription) = record_events(cx, &state);
    state.update(cx, |state, cx| {
        assert!(code_rows(state, 0) > 0);
        state.set_file_collapsed("first.txt", true, cx);
        assert!(state.is_file_collapsed("first.txt"));
        assert_eq!(code_rows(state, 0), 0);
        assert!(matches!(state.rows()[0], DisplayRow::File(0)));
        assert!(matches!(state.rows()[1], DisplayRow::File(1)));
        // Programmatic changes stay silent; the header toggle reports.
        state.toggle_file_collapsed(1, cx);
        assert!(state.is_file_collapsed("second.txt"));

        // Revealing a line expands its file.
        state.scroll_to_line(
            DiffLinePosition::new("first.txt", DiffSide::Modified, 2),
            cx,
        );
        assert!(!state.is_file_collapsed("first.txt"));

        // Paths identify files, so collapse survives a newer patch revision.
        state.set_files(DiffFile::parse(PATCH).unwrap().into_iter().rev(), cx);
        assert!(state.is_file_collapsed("second.txt"));
        state.scroll_to_file("first.txt", cx);
        assert_eq!(state.list().logical_scroll_top().item_ix, 1);
        state.scroll_to_file("missing.txt", cx);
        assert_eq!(state.list().logical_scroll_top().item_ix, 1);
    });
    assert!(matches!(
        events.borrow().as_slice(),
        [DiffEvent::FileCollapsed(path)] if path.as_str() == "second.txt"
    ));
}

#[gpui::test]
fn folds_expand_by_direction_and_short_ranges_stay_visible(cx: &mut TestAppContext) {
    let original = (1..=60)
        .map(|line| format!("line {line}\n"))
        .collect::<String>();
    let modified = original
        .replace("line 30\n", "changed 30\n")
        .replace("line 60\n", "changed 60\n");
    let file = super::document::fixture::modified("long.txt", &original, &modified);
    let state = cx.new(|cx| {
        DiffState::new([file], cx)
            .with_context_lines(Some(2))
            .with_expansion_lines(5)
    });
    let folds = |state: &DiffState| {
        state
            .rows()
            .iter()
            .filter_map(|row| match row {
                DisplayRow::Fold { pairs, .. } => Some(pairs.clone()),
                _ => None,
            })
            .collect::<Vec<_>>()
    };
    state.update(cx, |state, cx| {
        assert_eq!(folds(state), [0..27, 32..57]);
        state.expand_fold(0, 32..57, FoldExpansion::Down, cx);
        assert_eq!(folds(state), [0..27, 37..57]);
        state.expand_fold(0, 37..57, FoldExpansion::Up, cx);
        assert_eq!(folds(state), [0..27, 37..52]);
        state.expand_fold(0, 0..27, FoldExpansion::All, cx);
        assert_eq!(folds(state), [37..52]);
        state.collapse_unchanged(cx);
        assert_eq!(folds(state), [0..27, 32..57]);
    });

    // With a high threshold, ranges shorter than it are never collapsed.
    let file = super::document::fixture::modified("long.txt", &original, &modified);
    let state = cx.new(|cx| {
        DiffState::new([file], cx)
            .with_context_lines(Some(2))
            .with_min_collapsed_lines(26)
    });
    state.update(cx, |state, _| {
        assert_eq!(folds(state), [0..27]);
        assert_eq!(state.min_collapsed_lines(), 26);
        assert_eq!(state.expansion_lines(), 20);
    });
}

#[gpui::test]
fn line_selection_reports_a_gesture_lifecycle(cx: &mut TestAppContext) {
    let window = cx.open_window(size(px(640.), px(480.)), |_, _| Empty);
    let state = cx.new(|cx| DiffState::new(DiffFile::parse(PATCH).unwrap(), cx));
    let (events, _subscription) = record_events(cx, &state);
    let position = |side, line| DiffLinePosition::new("first.txt", side, line);
    cx.update_window(window.into(), |_, window, cx| {
        state.update(cx, |state, cx| {
            state.begin_line_selection(position(DiffSide::Original, 1), false, window, cx);
            state.drag_line_selection(position(DiffSide::Original, 2), cx);
            // A drag into another file does not extend the selection.
            state.drag_line_selection(
                DiffLinePosition::new("second.txt", DiffSide::Original, 10),
                cx,
            );
            // In Unified, dragging onto the addition crosses sides.
            state.drag_line_selection(position(DiffSide::Modified, 2), cx);
            state.end_line_selection(cx);
            state.end_line_selection(cx);
        });
    })
    .unwrap();
    let cross =
        DiffLineRange::new("first.txt", DiffSide::Original, 1, 2).with_end_side(DiffSide::Modified);
    let events = events.borrow();
    assert!(matches!(&events[0], DiffEvent::SelectionStarted(range)
        if *range == DiffLineRange::new("first.txt", DiffSide::Original, 1, 1)));
    assert!(
        matches!(&events[1], DiffEvent::SelectionChanged(Some(range))
        if *range == DiffLineRange::new("first.txt", DiffSide::Original, 1, 1))
    );
    assert!(
        matches!(&events[2], DiffEvent::SelectionChanged(Some(range))
        if *range == DiffLineRange::new("first.txt", DiffSide::Original, 1, 2))
    );
    assert!(matches!(&events[3], DiffEvent::SelectionChanged(Some(range)) if *range == cross));
    assert!(matches!(&events[4], DiffEvent::SelectionEnded(range) if *range == cross));
    assert_eq!(events.len(), 5);
    cx.update(|cx| {
        let state = state.read(cx);
        assert_eq!(state.selected_lines(), Some(cross.clone()));
        assert_eq!(state.selected_text(cx), "one\ntwo\nTWO\n");
    });
}

#[gpui::test]
fn programmatic_cross_side_ranges_clip_to_supplied_lines(cx: &mut TestAppContext) {
    let state = cx.new(|cx| DiffState::new(DiffFile::parse(PATCH).unwrap(), cx));
    state.update(cx, |state, cx| {
        state.set_selected_lines(
            Some(
                DiffLineRange::new("first.txt", DiffSide::Original, 2, 99)
                    .with_end_side(DiffSide::Modified),
            ),
            cx,
        );
        assert_eq!(
            state.selected_lines(),
            Some(
                DiffLineRange::new("first.txt", DiffSide::Original, 2, 3)
                    .with_end_side(DiffSide::Modified)
            )
        );
        assert_eq!(state.selected_text(cx), "two\nTWO\nthree\n");
        // A single-side range is normalized.
        state.set_selected_lines(
            Some(DiffLineRange::new("first.txt", DiffSide::Modified, 3, 1)),
            cx,
        );
        assert_eq!(
            state.selected_lines(),
            Some(DiffLineRange::new("first.txt", DiffSide::Modified, 1, 3))
        );
        state.list().scroll_to(ListOffset::default());
    });
}

#[test]
fn files_report_git_status_and_hidden_lines() {
    let files = DiffFile::parse(concat!(
        "diff --git a/new b/new\nnew file mode 100644\n--- /dev/null\n+++ b/new\n@@ -0,0 +1 @@\n+a\n",
        "diff --git a/old b/old\ndeleted file mode 100644\n--- a/old\n+++ /dev/null\n@@ -1 +0,0 @@\n-a\n",
        "diff --git a/from b/to\nsimilarity index 100%\nrename from from\nrename to to\n",
        "diff --git a/src b/copy\nsimilarity index 100%\ncopy from src\ncopy to copy\n",
        "diff --git a/edit b/edit\n--- a/edit\n+++ b/edit\n@@ -5,2 +5,2 @@\n x\n-y\n+z\n@@ -20 +20 @@\n-p\n+q\n",
    ))
    .unwrap();
    assert_eq!(
        files.iter().map(DiffFile::status).collect::<Vec<_>>(),
        [
            DiffFileStatus::Added,
            DiffFileStatus::Deleted,
            DiffFileStatus::Renamed,
            DiffFileStatus::Copied,
            DiffFileStatus::Modified,
        ]
    );
    let hunks = files[4].hunks();
    assert_eq!(hunks[0].hidden_lines_before(None), 4);
    assert_eq!(hunks[1].hidden_lines_before(Some(&hunks[0])), 13);
    let added = files[0].hunks();
    assert_eq!(added[0].hidden_lines_before(None), 0);
    let _ = DiffMode::Unified;
}

const MERGE: &str = "start\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> feature\nmiddle\n<<<<<<< HEAD\na\n||||||| base\nb\n=======\nc\n>>>>>>> other\nend\n";

#[gpui::test]
fn conflicts_project_their_parts_and_resolve_to_working_text(cx: &mut TestAppContext) {
    let file = DiffFile::parse_conflicts("merge.txt", MERGE).unwrap();
    let state = cx.new(|cx| {
        DiffState::new([file], cx)
            .with_mode(DiffMode::Split)
            .with_context_lines(None)
    });
    let (events, _subscription) = record_events(cx, &state);
    let conflict_rows = |state: &DiffState| {
        state
            .rows()
            .iter()
            .filter(|row| matches!(row, DisplayRow::Conflict { .. }))
            .count()
    };
    state.update(cx, |state, cx| {
        // Two parts for the first conflict, three with its base for the second.
        assert_eq!(conflict_rows(state), 5);
        assert_eq!(code_rows(state, 0), 8);
        assert_eq!(state.resolved_text("merge.txt"), None);
        state.resolve_conflict(
            "merge.txt",
            0,
            Some(super::DiffConflictResolution::Incoming),
            cx,
        );
        assert_eq!(conflict_rows(state), 4);
        assert_eq!(state.resolved_text("merge.txt"), None);
        state.choose_conflict(0, 1, Some(super::DiffConflictResolution::Both), cx);
        assert_eq!(
            state.resolved_text("merge.txt").as_deref(),
            Some("start\ntheirs\nmiddle\na\nc\nend\n")
        );
        assert_eq!(
            state.conflict_resolution("merge.txt", 1),
            Some(super::DiffConflictResolution::Both)
        );
        state.choose_conflict(0, 1, None, cx);
        assert_eq!(state.conflict_resolution("merge.txt", 1), None);
        // Out-of-range conflicts and other files are ignored.
        state.resolve_conflict(
            "merge.txt",
            9,
            Some(super::DiffConflictResolution::Current),
            cx,
        );
        assert_eq!(state.resolved_text("other.txt"), None);
    });
    let events = events.borrow();
    assert_eq!(events.len(), 2);
    assert!(events.iter().all(|event| matches!(
        event,
        DiffEvent::ConflictResolved(path, 1) if path.as_str() == "merge.txt"
    )));
}

#[gpui::test]
fn unchanged_files_show_every_line_without_folding(cx: &mut TestAppContext) {
    let text = (1..=40)
        .map(|line| format!("line {line}\n"))
        .collect::<String>();
    let state = cx.new(|cx| {
        DiffState::new([DiffFile::unchanged("notes.txt", &text)], cx).with_mode(DiffMode::Split)
    });
    state.update(cx, |state, cx| {
        assert_eq!(code_rows(state, 0), 40);
        assert!(
            !state
                .rows()
                .iter()
                .any(|row| matches!(row, DisplayRow::Fold { .. }))
        );
        state.set_selected_lines(
            Some(DiffLineRange::new("notes.txt", DiffSide::Modified, 2, 3)),
            cx,
        );
        assert_eq!(state.selected_text(cx), "line 2\nline 3\n");
    });
}

#[gpui::test]
fn builders_after_new_shape_the_prepared_emphasis(cx: &mut TestAppContext) {
    let patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-let total = price;\n+let total = cost;\n";
    let inline_count = |state: &gpui::Entity<DiffState>, cx: &mut TestAppContext| {
        state.update(cx, |state, cx| state.ensure_presentation(cx));
        cx.run_until_parked();
        state.read_with(cx, |state, _| {
            let file = &state.files()[0];
            let line = &file.lines(DiffSide::Modified)[0];
            state.presentations()[0]
                .as_ref()
                .expect("prepared in the background")
                .inline_changes(line, DiffSide::Modified, 0)
                .count()
        })
    };
    let words = cx.new(|cx| DiffState::new(DiffFile::parse(patch).unwrap(), cx));
    assert_eq!(inline_count(&words, cx), 1);
    let whole_lines =
        cx.new(|cx| DiffState::new(DiffFile::parse(patch).unwrap(), cx).with_inline_unit(None));
    assert_eq!(inline_count(&whole_lines, cx), 0);
    // Runtime changes invalidate earlier work, including an in-flight preparation.
    words.update(cx, |state, cx| {
        state.set_inline_unit(None, cx);
        state.set_inline_unit(Some(super::DiffInlineUnit::Character), cx);
    });
    assert!(inline_count(&words, cx) > 0);
    words.update(cx, |state, cx| state.set_inline_max_line_length(5, cx));
    assert_eq!(inline_count(&words, cx), 0);
    words.update(cx, |state, cx| {
        state.set_inline_max_line_length(2048, cx);
        state.set_inline_unit(Some(super::DiffInlineUnit::Word), cx);
    });
    assert_eq!(inline_count(&words, cx), 1);
}

#[gpui::test]
fn changing_presentation_options_keeps_selection_and_scroll(cx: &mut TestAppContext) {
    let state = cx.new(|cx| DiffState::new(DiffFile::parse(PATCH).unwrap(), cx));
    let (events, _subscription) = record_events(cx, &state);
    state.update(cx, |state, cx| {
        let range = DiffLineRange::new("second.txt", DiffSide::Modified, 10, 10);
        state.set_selected_lines(Some(range.clone()), cx);
        state.scroll_to_line(range.start_position(), cx);
        let top = state.list().logical_scroll_top();
        state.set_inline_unit(Some(super::DiffInlineUnit::Character), cx);
        state.set_inline_max_line_length(2048, cx);
        state.set_syntax_max_line_length(4096, cx);
        state.set_expansion_lines(5, cx);
        state.set_min_collapsed_lines(4, cx);
        assert_eq!(state.selected_lines(), Some(range));
        assert_eq!(state.list().logical_scroll_top().item_ix, top.item_ix);
        assert_eq!(state.inline_unit(), Some(super::DiffInlineUnit::Character));
        assert_eq!(state.inline_max_line_length(), 2048);
        assert_eq!(state.syntax_max_line_length(), 4096);
        assert_eq!(state.expansion_lines(), 5);
        assert_eq!(state.min_collapsed_lines(), 4);
        // None disables emphasis, without replacing the entity or patch.
        state.set_inline_unit(None, cx);
        assert!(state.inline_unit().is_none());
        assert_eq!(state.files().len(), 2);
    });
    assert!(events.borrow().is_empty());
}
