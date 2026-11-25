use anyhow::{Context, Result, bail, ensure};
use chrono::{DateTime, Utc};
use meep_ingest::Event;
use meep_topic::Watch;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Mapping {
    #[serde(default)]
    items: String,
    id: String,
    author: Pointers,
    text: String,
    timestamp: String,
    thread: Option<Pointers>,
    #[serde(default)]
    versioned_id: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(untagged)]
enum Pointers {
    One(String),
    FirstPresent(Vec<String>),
}

impl Pointers {
    fn paths(&self) -> &[String] {
        match self {
            Self::One(path) => std::slice::from_ref(path),
            Self::FirstPresent(paths) => paths,
        }
    }

    fn select<'a>(&self, item: &'a Value) -> Option<&'a Value> {
        self.paths()
            .iter()
            .find_map(|path| item.pointer(path).filter(|v| !v.is_null()))
    }
}

pub(super) struct Row {
    pub event: Event,
    pub raw_timestamp: Value,
}

fn scalar(value: &Value) -> Result<String> {
    match value {
        Value::String(s) if !s.is_empty() => Ok(s.clone()),
        Value::Number(n) => Ok(n.to_string()),
        _ => bail!("expected a nonempty string or number"),
    }
}

pub(super) fn timestamp(s: &str) -> Result<DateTime<Utc>> {
    if let Ok(time) = DateTime::parse_from_rfc3339(s) {
        return Ok(time.to_utc());
    }
    // Parse Slack's decimal Unix timestamp without rounding away microseconds.
    let number = s.strip_prefix('-').unwrap_or(s);
    let (seconds, fraction) = number.split_once('.').unwrap_or((number, ""));
    ensure!(!number.ends_with('.'), "empty fractional seconds");
    ensure!(
        !seconds.is_empty()
            && seconds.bytes().all(|c| c.is_ascii_digit())
            && fraction.len() <= 9
            && fraction.bytes().all(|c| c.is_ascii_digit()),
        "expected RFC 3339 or Unix seconds"
    );
    let fraction: i64 = format!("{fraction:0<9}").parse()?;
    let whole: i64 = seconds.parse()?;
    let (whole, nanos) = if s.starts_with('-') && fraction > 0 {
        (-whole - 1, 1_000_000_000 - fraction)
    } else if s.starts_with('-') {
        (-whole, 0)
    } else {
        (whole, fraction)
    };
    DateTime::from_timestamp(whole, nanos.try_into()?).context("timestamp out of range")
}

pub(super) fn validate_pointer(path: &str) -> Result<()> {
    ensure!(
        path.is_empty() || path.starts_with('/'),
        "invalid JSON pointer {path}"
    );
    for (i, _) in path.match_indices('~') {
        ensure!(
            matches!(path.as_bytes().get(i + 1), Some(b'0' | b'1')),
            "invalid JSON pointer escape in {path}"
        );
    }
    Ok(())
}

impl Mapping {
    pub fn validate(&self) -> Result<()> {
        ensure!(!self.author.paths().is_empty(), "missing author pointer");
        for path in [&self.items, &self.id, &self.text, &self.timestamp]
            .into_iter()
            .chain(self.author.paths())
            .chain(self.thread.iter().flat_map(Pointers::paths))
        {
            validate_pointer(path)?;
        }
        Ok(())
    }

    pub fn rows(&self, response: &Value, watch: &Watch) -> Result<Vec<Row>> {
        let items = response
            .pointer(&self.items)
            .with_context(|| format!("missing items at JSON pointer '{}'", self.items))?;
        let items = match items {
            Value::Array(values) => values.as_slice(),
            Value::Object(_) => std::slice::from_ref(items),
            _ => bail!(
                "expected an object or array at items pointer '{}'",
                self.items
            ),
        };
        items.iter().map(|item| self.row(item, watch)).collect()
    }

    fn row(&self, item: &Value, watch: &Watch) -> Result<Row> {
        let field = |path: &str| {
            item.pointer(path)
                .with_context(|| format!("missing field at {path}"))
        };
        let id = scalar(field(&self.id)?).context("invalid event id")?;
        let raw_timestamp = field(&self.timestamp)?;
        let at = timestamp(&scalar(raw_timestamp)?)
            .with_context(|| format!("invalid timestamp at {}", self.timestamp))?;
        let external_id = if self.versioned_id {
            json!([id, at]).to_string()
        } else {
            id
        };
        let thread_hint = self
            .thread
            .as_ref()
            .and_then(|p| p.select(item))
            .map(scalar)
            .transpose()?;
        Ok(Row {
            raw_timestamp: raw_timestamp.clone(),
            event: Event {
                connection: watch.connection.clone(),
                kind: watch.kind.clone(),
                channel: watch.key.clone(),
                external_id,
                thread_hint,
                author: scalar(
                    self.author
                        .select(item)
                        .with_context(|| format!("missing author at {:?}", self.author.paths()))?,
                )
                .context("invalid author")?,
                at,
                text: field(&self.text)?
                    .as_str()
                    .context("expected event text string")?
                    .to_owned(),
                attributes: item.clone(),
            },
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decimal_seconds_preserve_every_digit_of_a_slack_timestamp() -> Result<()> {
        let ts = timestamp("1737891234.000000019")?;
        assert_eq!(ts.timestamp(), 1737891234);
        assert_eq!(ts.timestamp_subsec_nanos(), 19);
        assert_eq!(timestamp("1737891234.1")?.timestamp_subsec_micros(), 100000);
        assert_eq!(timestamp("-0.1")?.timestamp_millis(), -100);
        Ok(())
    }

    #[test]
    fn malformed_timestamps_and_overflow_return_errors() {
        for invalid in [
            "yesterday",
            ".123",
            "999999999999999999999",
            "14.9876543210",
            "2.4a",
        ] {
            assert!(timestamp(invalid).is_err(), "{invalid}");
        }
    }

    #[test]
    fn a_slack_thread_root_and_bot_reply_use_the_first_available_source_pointer() -> Result<()> {
        let mapping: Mapping = serde_json::from_value(json!({
            "id":"/ts","text":"/text","timestamp":"/ts",
            "author":["/user","/bot_id"],"thread":["/thread_ts","/ts"]
        }))?;
        mapping.validate()?;
        let watch: Watch = serde_json::from_value(
            json!({"id":uuid::Uuid::nil(),"connection":"slack","key":"C1","kind":"channel","label":"Design"}),
        )?;
        let rows = mapping.rows(
            &json!([
                {"ts":"10.100","user":"U1","text":"root"},
                {"ts":"11.100","thread_ts":"10.100","user":null,"bot_id":"B1","text":"reply"}
            ]),
            &watch,
        )?;
        assert_eq!(rows[0].event.thread_hint.as_deref(), Some("10.100"));
        assert_eq!(rows[0].event.thread_hint, rows[1].event.thread_hint);
        assert_eq!(rows[1].event.author, "B1");
        Ok(())
    }
}
