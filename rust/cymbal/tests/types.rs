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
}
