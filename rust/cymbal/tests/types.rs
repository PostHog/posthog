use std::str::FromStr;

use common_types::ClickHouseEvent;
use cymbal::{
    frames::{Frame, RawFrame},
    types::{RawErrProps, Stacktrace},
};
use serde_json::Value;

#[test]
fn serde_passthrough() {
    let raw: &'static str = include_str!("./static/raw_ch_exception_list.json");
    let before: Value = serde_json::from_str(raw).unwrap();
    let raw: ClickHouseEvent = serde_json::from_str(raw).unwrap();

    let before_properties: Value = serde_json::from_str(raw.properties.as_ref().unwrap()).unwrap();
    let properties_parsed: RawErrProps =
        serde_json::from_str(raw.properties.as_ref().unwrap()).unwrap();

    let properties_raw = serde_json::to_string(&properties_parsed).unwrap();
    let after_properties = Value::from_str(&properties_raw).unwrap();

    assert_eq!(before_properties, after_properties);

    let after = serde_json::to_string(&raw).unwrap();
    let after = Value::from_str(&after).unwrap();

    assert_eq!(before, after)
}

#[test]
fn python_exceptions() {
    let props: RawErrProps =
        serde_json::from_str(include_str!("./static/python_err_props.json")).unwrap();

    let frames = props
        .exception_list
        .iter()
        .map(|e| e.stack.clone().unwrap())
        .flat_map(|t| {
            let Stacktrace::Raw { frames } = t else {
                panic!("Expected a Raw stacktrace")
            };
            frames
        })
        .map(|f| {
            let RawFrame::Python(f) = f else {
                panic!("Expected a Python frame")
            };
            let f: Frame = (&f).into();
            f
        })
        .collect::<Vec<_>>();

    assert_eq!(frames.len(), 31);
}

#[test]
fn node_exceptions() {
    let props: RawErrProps =
        serde_json::from_str(include_str!("./static/node_err_props.json")).unwrap();

    let frames = props
        .exception_list
        .iter()
        .map(|e| e.stack.clone().unwrap())
        .flat_map(|t| {
            let Stacktrace::Raw { frames } = t else {
                panic!("Expected a Raw stacktrace")
            };
            frames
        })
        .map(|f| {
            let RawFrame::JavaScriptNode(f) = f else {
                panic!("Expected a Node frame")
            };
            let f: Frame = (&f).into();
            f
        })
        .collect::<Vec<_>>();

    assert_eq!(frames.len(), 4);
    let context = frames[3].context.as_ref().unwrap();
    assert_eq!(context.line.number, 27);
    assert_eq!(
        context.line.line,
        "  throw new Error(\"My first PostHog error!\");"
    );
    assert_eq!(context.before.len(), 7);
    // Adjacent to context line (lineno - 1); pre_context order is reversed into display order
    assert_eq!(context.before[0].number, 26);
    assert_eq!(
        context.before[0].line,
        "  posthog.capture({ event: \"Test event\", distinctId: \"test\" });"
    );
    assert_eq!(context.before[6].number, 20);
    assert_eq!(context.before[6].line, "});");
}

#[test]
fn php_exceptions() {
    let props: RawErrProps =
        serde_json::from_str(include_str!("./static/php_err_props.json")).unwrap();

    let frames = props
        .exception_list
        .iter()
        .map(|e| e.stack.clone().unwrap())
        .flat_map(|t| {
            let Stacktrace::Raw { frames } = t else {
                panic!("Expected a Raw stacktrace")
            };
            frames
        })
        .map(|f| {
            let RawFrame::Php(f) = f else {
                panic!("Expected a PHP frame")
            };
            let f: Frame = (&f).into();
            f
        })
        .collect::<Vec<_>>();

    assert_eq!(frames.len(), 2);
    assert_eq!(frames[0].lang, "php");
    assert_eq!(frames[0].source.as_deref(), Some("ExceptionCapture.php"));
    assert_eq!(
        frames[0].resolved_name.as_deref(),
        Some("PostHog\\ExceptionCapture::buildParsedException")
    );
    let context = frames[0].context.as_ref().unwrap();
    assert_eq!(context.line.number, 42);
    assert_eq!(context.line.line, "throw new \\RuntimeException('boom');");
    assert_eq!(context.before.len(), 2);
    assert_eq!(context.before[0].number, 41);
    assert_eq!(context.before[0].line, "    $throwLine = __LINE__ + 1;");
    assert_eq!(context.before[1].number, 40);
    assert_eq!(context.before[1].line, "try {");
    assert_eq!(context.after.len(), 2);
    assert_eq!(context.after[0].number, 43);
    assert_eq!(context.after[0].line, "} catch (\\RuntimeException $e) {");
    assert_eq!(context.after[1].number, 44);
    assert_eq!(context.after[1].line, "    return [$e, $throwLine];");
    assert_eq!(frames[1].mangled_name, "<unknown>");
    assert_eq!(frames[1].resolved_name, None);
}
