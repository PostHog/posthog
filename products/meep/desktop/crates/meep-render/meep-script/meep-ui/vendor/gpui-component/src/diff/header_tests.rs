use std::{cell::RefCell, rc::Rc};

use gpui::{AppContext, ParentElement as _, TestAppContext, div};

use super::{
    Diff, DiffAnnotation, DiffFile, DiffLinePosition, DiffSide, DiffState, document::fixture,
};

#[gpui::test]
fn test_diff_builder(cx: &mut TestAppContext) {
    cx.update(crate::init);
    let document = fixture::document(
        Some(("before.rs", "let value = 1;\n")),
        Some(("after.rs", "let value = 2;\n")),
    );
    let state = cx.new(|cx| DiffState::new([document.clone()], cx));
    let defaults = Diff::new(&state);
    assert_eq!(defaults.state.entity_id(), state.entity_id());
    assert!(defaults.header_visible && defaults.line_number);
    assert!(defaults.syntax_highlight);
    assert!(defaults.annotations.items.is_empty());
    assert!(defaults.header.content.is_none());
    assert!(defaults.annotation_content.is_none());

    let header_calls = Rc::new(RefCell::new(Vec::new()));
    let position = DiffLinePosition::new("after.rs", DiffSide::Modified, 1);
    let annotation = DiffAnnotation::line("review-comment", position.clone());
    let annotation_calls = Rc::new(RefCell::new(Vec::new()));
    let diff = Diff::new(&state)
        .header_visible(false)
        .line_number(false)
        .syntax_highlight(false)
        .annotations([annotation.clone()])
        .render_header({
            let header_calls = header_calls.clone();
            move |document: &DiffFile, _, _| {
                header_calls.borrow_mut().push((
                    document.original_path().cloned(),
                    document.modified_path().cloned(),
                ));
                div().child("header")
            }
        })
        .render_annotation({
            let annotation_calls = annotation_calls.clone();
            move |annotation, _, _| {
                assert_eq!(annotation.id(), &"review-comment".into());
                annotation_calls
                    .borrow_mut()
                    .push(annotation.position().cloned().unwrap());
                div().child("Review comment")
            }
        });

    assert_eq!(diff.state.entity_id(), state.entity_id());
    assert!(!diff.header_visible && !diff.line_number);
    assert!(!diff.syntax_highlight);
    assert_eq!(diff.annotations.items.len(), 1);
    assert_eq!(diff.annotations.items[0].id(), annotation.id());
    assert_eq!(diff.annotations.items[0].position(), Some(&position));
    assert_eq!(diff.annotations.lines[&position], [0]);

    // Existing consumers keep the original builder spellings.
    let compatibility = Diff::new(&state)
        .header(|_, _, _| div().child("header"))
        .header_prefix(|_, _, _| div().child("prefix"))
        .header_title_suffix(|_, _, _| div().child("title suffix"))
        .header_suffix(|_, _, _| div().child("suffix"))
        .annotation_content(|_, _, _| div().child("annotation"));
    assert!(compatibility.header.content.is_some());
    assert!(compatibility.header.prefix.is_some());
    assert!(compatibility.header.title_suffix.is_some());
    assert!(compatibility.header.suffix.is_some());
    assert!(compatibility.annotation_content.is_some());

    let window = cx.add_empty_window();
    window.update(|window, cx| {
        let render = diff.header.content.as_ref().unwrap();
        let _ = render(&document, window, cx);
        let render = diff.annotation_content.as_ref().unwrap();
        let _ = render(&diff.annotations.items[0], window, cx);
    });
    assert_eq!(
        header_calls.borrow().as_slice(),
        &[(Some("before.rs".into()), Some("after.rs".into()))]
    );
    assert_eq!(annotation_calls.borrow().as_slice(), &[position]);
}
