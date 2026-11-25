use super::{DiffSide, document::fixture, has_line_ending_change};

#[test]
fn ending_changes_retain_counterparts_and_exact_source() {
    for (original, modified, ending_only) in [
        ("same\n", "same", true),
        ("same\r\n", "same\n", true),
        ("same", "same\r\n", true),
        ("old\r\n", "new\n", false),
        ("\t\n", "    \n", false),
    ] {
        let document = fixture::modified("a.txt", original, modified);
        assert!(document.has_changes());
        for side in [DiffSide::Original, DiffSide::Modified] {
            let line = &document.lines(side)[0];
            assert_eq!(line.counterpart(), Some(0));
            assert_eq!(
                has_line_ending_change(&document, side, 0, line.counterpart()),
                ending_only
            );
            assert_eq!(document.text_for_lines(side, 1, 1), document.source(side));
        }
    }
}

#[test]
fn missing_files_and_blank_lines_have_no_false_counterparts() {
    for document in [
        fixture::document(None, Some(("empty.txt", ""))),
        fixture::document(Some(("empty.txt", "")), None),
    ] {
        assert!(document.has_changes());
        assert_eq!((document.additions(), document.deletions()), (0, 0));
        assert_eq!(document.lines_count(DiffSide::Original), 0);
        assert_eq!(document.lines_count(DiffSide::Modified), 0);
    }
    for (original, modified, side) in [
        ("", "\n", DiffSide::Modified),
        ("\n", "", DiffSide::Original),
    ] {
        let document = fixture::modified("a.txt", original, modified);
        let line = &document.lines(side)[0];
        assert!(line.text().is_empty());
        assert_eq!(line.counterpart(), None);
        assert!(!has_line_ending_change(
            &document,
            side,
            0,
            line.counterpart()
        ));
        assert_eq!(document.text_for_lines(side, 1, 1), "\n");
    }
}
