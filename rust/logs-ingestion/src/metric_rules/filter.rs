//! The narrow interface to the filter-group code in `crate::sampling` and `crate::filter_group`.

use std::fmt;
use std::sync::Arc;

use crate::filter_group::{match_filter_group, FilterGroupNode};
use crate::js::JsValue;
use crate::property_filter::coerce::JsTypeError;
use crate::record::LogRecord;

pub trait FilterGroupMatcher: Send + Sync + fmt::Debug {
    /// `matchFilterGroup(group, record)`. `Err` is a throw, which `tallyRecords` counts.
    fn matches(&self, record: &LogRecord) -> Result<bool, JsTypeError>;
}

/// `parseFilterGroup(raw)`: `Ok(None)` when the value is not a valid filter group, and `Err`
/// when the TypeScript throws.
pub type FilterGroupParser =
    fn(&JsValue) -> Result<Option<Arc<dyn FilterGroupMatcher>>, JsTypeError>;

impl FilterGroupMatcher for FilterGroupNode {
    fn matches(&self, record: &LogRecord) -> Result<bool, JsTypeError> {
        match_filter_group(self, record)
    }
}

pub fn parse_filter_group(
    raw: &JsValue,
) -> Result<Option<Arc<dyn FilterGroupMatcher>>, JsTypeError> {
    Ok(crate::sampling::parse_filter_group(raw)?
        .map(|g| Arc::new(g) as Arc<dyn FilterGroupMatcher>))
}
