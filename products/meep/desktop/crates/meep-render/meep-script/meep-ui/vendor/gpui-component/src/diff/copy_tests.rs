use super::{DiffFile, DiffLineRange, DiffSide, document::fixture};

/// Copies a normalized range, as gutter and keyboard selection do.
fn copy(document: &DiffFile, side: DiffSide, start: usize, end: usize) -> String {
    let range = DiffLineRange::new("", side, start, end);
    document.text_for_lines(
        side,
        range.start().min(range.end()),
        range.start().max(range.end()),
    )
}

#[test]
fn copying_source_line_ranges_preserves_whitespace_unicode_and_eof() {
    let original = "\t旧值 🦀\r\n\r\n尾部\t  ";
    let modified = "\t新值 👩‍💻\r\n\r\n尾部\t  \r\n";
    let document = fixture::modified("review.txt", original, modified);

    for (side, source, first_line, last_line) in [
        (DiffSide::Original, original, "\t旧值 🦀\r\n", "尾部\t  "),
        (
            DiffSide::Modified,
            modified,
            "\t新值 👩‍💻\r\n",
            "尾部\t  \r\n",
        ),
    ] {
        // Reversed endpoints and a zero endpoint still copy complete source lines.
        assert_eq!(copy(&document, side, usize::MAX, 0), source);
        assert_eq!(copy(&document, side, 0, 0), first_line);
        assert_eq!(copy(&document, side, 2, 2), "\r\n");
        assert_eq!(copy(&document, side, 3, usize::MAX), last_line);
        assert_eq!(copy(&document, side, 4, usize::MAX), "");
    }
}

#[test]
fn copying_added_deleted_and_empty_files_respects_the_requested_side() {
    let source = "\t中文 🦀\r\n末行";
    for (document, present, missing) in [
        (
            fixture::document(None, Some(("new.txt", source))),
            DiffSide::Modified,
            DiffSide::Original,
        ),
        (
            fixture::document(Some(("old.txt", source)), None),
            DiffSide::Original,
            DiffSide::Modified,
        ),
    ] {
        assert_eq!(copy(&document, present, 1, usize::MAX), source);
        assert_eq!(copy(&document, missing, 1, usize::MAX), "");
        assert_eq!(copy(&document, present, usize::MAX, usize::MAX), "");
    }

    let empty = fixture::modified("empty.txt", "", "");
    for side in [DiffSide::Original, DiffSide::Modified] {
        assert_eq!(copy(&empty, side, 0, usize::MAX), "");
    }
}
