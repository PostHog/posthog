//! Golden tests pinning the automatic fingerprint algorithm bit-for-bit.
//!
//! The snapshots were recorded against the pre-`FingerprintStrategy` implementation, so any
//! refactor of the fingerprinting code must reproduce them exactly — both the SHA-512 `value`
//! and the user-facing `record`. A change here re-groups live error-tracking issues; treat a
//! snapshot diff as a data-migration concern, never an "accept and move on".

use common_types::error_tracking::FrameId;
use common_types::ClickHouseEvent;
use cymbal::fingerprinting::Fingerprint;
use cymbal::frames::Frame;
use cymbal::types::{Exception, RawErrProps, Stacktrace};

#[allow(clippy::too_many_arguments)]
fn frame(
    mangled: &str,
    source: Option<&str>,
    module: Option<&str>,
    resolved_name: Option<&str>,
    resolved: bool,
    in_app: bool,
    line: Option<u32>,
    column: Option<u32>,
) -> Frame {
    Frame {
        frame_id: FrameId::new(String::new(), 1, 0),
        mangled_name: mangled.to_string(),
        line,
        column,
        source: source.map(String::from),
        in_app,
        resolved_name: resolved_name.map(String::from),
        resolved,
        resolve_failure: None,
        lang: "javascript".to_string(),
        junk_drawer: None,
        code_variables: None,
        context: None,
        release: None,
        synthetic: false,
        suspicious: false,
        module: module.map(String::from),
    }
}

fn exception(exc_type: &str, message: &str, stack: Option<Stacktrace>) -> Exception {
    Exception {
        exception_id: Some("00000000-0000-0000-0000-000000000000".to_string()),
        exception_type: exc_type.to_string(),
        exception_message: message.to_string(),
        mechanism: Default::default(),
        module: Default::default(),
        thread_id: None,
        stack,
    }
}

fn resolved_stack(frames: Vec<Frame>) -> Option<Stacktrace> {
    Some(Stacktrace::Resolved { frames })
}

fn snapshot(name: &str, exceptions: Vec<Exception>) {
    let fingerprint = Fingerprint::from_exception_list(&exceptions.into());
    insta::assert_json_snapshot!(name, fingerprint);
}

#[test]
fn golden_no_stack() {
    snapshot(
        "no_stack",
        vec![exception(
            "TypeError",
            "Cannot read property 'foo' of undefined",
            None,
        )],
    );
}

#[test]
fn golden_raw_stack_uses_type_and_message() {
    // A raw (unresolved-typed) stack contributes nothing beyond type + message.
    let raw_frame = serde_json::from_value(serde_json::json!({
        "platform": "web:javascript",
        "function": "eF",
        "filename": "chunk-PGUQKT6S.js",
        "lineno": 64,
        "colno": 25112,
        "in_app": true
    }))
    .expect("valid raw JS frame");
    snapshot(
        "raw_stack",
        vec![exception(
            "ReferenceError",
            "x is not defined",
            Some(Stacktrace::Raw {
                frames: vec![raw_frame],
            }),
        )],
    );
}

#[test]
fn golden_all_resolved_in_app() {
    snapshot(
        "all_resolved_in_app",
        vec![exception(
            "TypeError",
            "Cannot read property 'foo' of undefined",
            resolved_stack(vec![
                frame(
                    "foo",
                    Some("http://example.com/alpha/foo.js"),
                    None,
                    Some("bar"),
                    true,
                    true,
                    Some(10),
                    Some(5),
                ),
                frame(
                    "bar",
                    Some("http://example.com/bar.js"),
                    Some("app.module"),
                    Some("baz"),
                    true,
                    true,
                    Some(20),
                    Some(15),
                ),
            ]),
        )],
    );
}

#[test]
fn golden_mixed_resolved_unresolved_ignores_unresolved() {
    snapshot(
        "mixed_resolved_unresolved",
        vec![exception(
            "TypeError",
            "Cannot read property 'foo' of undefined",
            resolved_stack(vec![
                frame(
                    "foo",
                    Some("http://example.com/alpha/foo.js"),
                    None,
                    Some("bar"),
                    true,
                    true,
                    Some(10),
                    Some(5),
                ),
                frame("xyz", None, None, None, false, true, Some(30), Some(25)),
            ]),
        )],
    );
}

#[test]
fn golden_no_resolved_frames_uses_all_in_app() {
    snapshot(
        "no_resolved_frames",
        vec![exception(
            "TypeError",
            "Cannot read property 'foo' of undefined",
            resolved_stack(vec![
                frame(
                    "foo",
                    Some("http://example.com/alpha/foo.js"),
                    None,
                    None,
                    false,
                    true,
                    Some(10),
                    Some(5),
                ),
                frame("xyz", None, None, None, false, true, Some(30), Some(25)),
            ]),
        )],
    );
}

#[test]
fn golden_no_in_app_frames_uses_first_frame() {
    snapshot(
        "no_in_app_frames",
        vec![exception(
            "TypeError",
            "Cannot read property 'foo' of undefined",
            resolved_stack(vec![
                frame(
                    "vendor_a",
                    Some("http://example.com/vendor.js"),
                    None,
                    Some("vendorA"),
                    true,
                    false,
                    Some(1),
                    Some(2),
                ),
                frame(
                    "vendor_b",
                    Some("http://example.com/vendor.js"),
                    None,
                    Some("vendorB"),
                    true,
                    false,
                    Some(3),
                    Some(4),
                ),
            ]),
        )],
    );
}

#[test]
fn golden_chained_exceptions() {
    snapshot(
        "chained_exceptions",
        vec![
            exception(
                "WrapperError",
                "wrapped",
                resolved_stack(vec![frame(
                    "outer",
                    Some("http://example.com/outer.js"),
                    None,
                    Some("outerFn"),
                    true,
                    true,
                    Some(1),
                    Some(1),
                )]),
            ),
            exception("RootError", "root cause", None),
        ],
    );
}

#[test]
fn golden_static_raw_ch_exception_list() {
    // Real capture-shaped event: `properties` is a JSON string holding RawErrProps.
    let event: ClickHouseEvent =
        serde_json::from_str(include_str!("./static/raw_ch_exception_list.json"))
            .expect("valid ClickHouseEvent fixture");
    let props: RawErrProps =
        serde_json::from_str(event.properties.as_deref().expect("fixture has properties"))
            .expect("valid RawErrProps");
    snapshot(
        "static_raw_ch_exception_list",
        props.exception_list.iter().cloned().collect(),
    );
}
