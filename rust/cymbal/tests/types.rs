use std::str::FromStr;

use common_types::ClickHouseEvent;
use cymbal::types::ErrProps;
use serde_json::Value;

#[test]
fn serde_passthrough() {
    let raw: &'static str = include_str!("./static/raw_ch_exception_list.json");
    let before: Value = serde_json::from_str(raw).unwrap();
    let raw: ClickHouseEvent = serde_json::from_str(raw).unwrap();

    let before_properties: Value = serde_json::from_str(raw.properties.as_ref().unwrap()).unwrap();
    let properties_parsed: ErrProps =
        serde_json::from_str(raw.properties.as_ref().unwrap()).unwrap();

    let properties_raw = serde_json::to_string(&properties_parsed).unwrap();
    let after_properties = Value::from_str(&properties_raw).unwrap();

    assert_eq!(before_properties, after_properties);

    let after = serde_json::to_string(&raw).unwrap();
    let after = Value::from_str(&after).unwrap();

    assert_eq!(before, after)
}
