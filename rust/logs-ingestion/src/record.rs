//! A stage can set a property the writer schema lacks, which later stages read and the encoder ignores, so `LogRecord` keeps it in `extra`.

use std::sync::Arc;

use crate::avro::{AvroMap, AvroValue};

#[derive(Debug, Clone, PartialEq)]
pub struct LogRecord {
    pub fields: Vec<(Arc<str>, AvroValue)>,
    pub extra: Vec<(Arc<str>, AvroValue)>,
}

impl LogRecord {
    pub fn from_value(value: AvroValue) -> Self {
        let fields = match value {
            AvroValue::Record(fields) => fields,
            _ => Vec::new(),
        };
        Self {
            fields,
            extra: Vec::new(),
        }
    }

    /// The value to encode. Extra properties are dropped, as avsc ignores them.
    pub fn into_value(self) -> AvroValue {
        AvroValue::Record(self.fields)
    }

    pub fn to_value(&self) -> AvroValue {
        AvroValue::Record(self.fields.clone())
    }

    /// `None` for a missing property (JavaScript `undefined`).
    pub fn get(&self, name: &str) -> Option<&AvroValue> {
        self.fields
            .iter()
            .chain(self.extra.iter())
            .find(|(k, _)| &**k == name)
            .map(|(_, v)| v)
    }

    pub fn get_mut(&mut self, name: &str) -> Option<&mut AvroValue> {
        if let Some(i) = self.fields.iter().position(|(k, _)| &**k == name) {
            return Some(&mut self.fields[i].1);
        }
        self.extra
            .iter_mut()
            .find(|(k, _)| &**k == name)
            .map(|(_, v)| v)
    }

    pub fn has_field(&self, name: &str) -> bool {
        self.fields.iter().any(|(k, _)| &**k == name)
    }

    pub fn set(&mut self, name: &str, value: AvroValue) {
        match self.get_mut(name) {
            Some(slot) => *slot = value,
            None => self.extra.push((Arc::from(name), value)),
        }
    }

    pub fn get_str(&self, name: &str) -> Option<&str> {
        self.get(name).and_then(AvroValue::as_str)
    }

    pub fn get_i64(&self, name: &str) -> Option<i64> {
        self.get(name).and_then(AvroValue::as_i64)
    }

    pub fn get_map(&self, name: &str) -> Option<&AvroMap> {
        self.get(name).and_then(AvroValue::as_map)
    }

    pub fn get_map_mut(&mut self, name: &str) -> Option<&mut AvroMap> {
        match self.get_mut(name) {
            Some(AvroValue::Map(m)) => Some(m),
            _ => None,
        }
    }

    pub fn get_bytes(&self, name: &str) -> Option<&[u8]> {
        self.get(name).and_then(AvroValue::as_bytes)
    }

    pub fn uuid(&self) -> Option<&str> {
        self.get_str("uuid")
    }
    pub fn trace_id(&self) -> Option<&[u8]> {
        self.get_bytes("trace_id")
    }
    pub fn span_id(&self) -> Option<&[u8]> {
        self.get_bytes("span_id")
    }
    pub fn timestamp(&self) -> Option<i64> {
        self.get_i64("timestamp")
    }
    pub fn observed_timestamp(&self) -> Option<i64> {
        self.get_i64("observed_timestamp")
    }
    pub fn body(&self) -> Option<&str> {
        self.get_str("body")
    }
    pub fn severity_text(&self) -> Option<&str> {
        self.get_str("severity_text")
    }
    pub fn severity_number(&self) -> Option<i64> {
        self.get_i64("severity_number")
    }
    pub fn service_name(&self) -> Option<&str> {
        self.get_str("service_name")
    }
    pub fn resource_attributes(&self) -> Option<&AvroMap> {
        self.get_map("resource_attributes")
    }
    pub fn instrumentation_scope(&self) -> Option<&str> {
        self.get_str("instrumentation_scope")
    }
    pub fn event_name(&self) -> Option<&str> {
        self.get_str("event_name")
    }
    pub fn attributes(&self) -> Option<&AvroMap> {
        self.get_map("attributes")
    }
    pub fn attributes_mut(&mut self) -> Option<&mut AvroMap> {
        self.get_map_mut("attributes")
    }
    pub fn bytes_uncompressed(&self) -> Option<i64> {
        self.get_i64("bytes_uncompressed")
    }
    pub fn retention_days(&self) -> Option<i64> {
        self.get_i64("retention_days")
    }
    pub fn pattern(&self) -> Option<&str> {
        self.get_str("pattern")
    }
    pub fn pattern_version(&self) -> Option<i64> {
        self.get_i64("pattern_version")
    }
    pub fn name(&self) -> Option<&str> {
        self.get_str("name")
    }
    pub fn kind(&self) -> Option<i64> {
        self.get_i64("kind")
    }
    pub fn status_code(&self) -> Option<i64> {
        self.get_i64("status_code")
    }
    /// Span end time, in microseconds.
    pub fn end_time(&self) -> Option<i64> {
        self.get_i64("end_time")
    }

    pub fn set_retention_days(&mut self, days: i64) {
        self.set("retention_days", AvroValue::Int(days));
    }
    pub fn set_pattern(&mut self, pattern: String, version: i64) {
        self.set("pattern", AvroValue::String(pattern));
        self.set("pattern_version", AvroValue::Int(version));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_property_outside_the_schema_is_readable_but_not_encoded() {
        let mut record = LogRecord::from_value(AvroValue::Record(vec![(
            Arc::from("body"),
            AvroValue::String("b".into()),
        )]));
        record.set("pattern", AvroValue::String("p".into()));
        assert_eq!(record.pattern(), Some("p"));
        assert!(!record.has_field("pattern"));
        assert_eq!(
            record.into_value(),
            AvroValue::Record(vec![(Arc::from("body"), AvroValue::String("b".into()))])
        );
    }
}
