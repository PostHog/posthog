use std::sync::{Arc, Mutex};

use async_trait::async_trait;
pub use bytes::Bytes;

pub const DLQ_OUTPUT: &str = "dlq";
pub const INGESTION_WARNINGS_OUTPUT: &str = "ingestion_warnings";

#[derive(Debug, Clone, Default, PartialEq)]
pub struct KafkaMessage {
    pub topic: String,
    pub partition: i32,
    pub offset: i64,
    pub key: Option<Vec<u8>>,
    pub value: Option<Bytes>,
    /// In wire order. A header can repeat, as in Kafka.
    pub headers: Vec<(String, Option<Vec<u8>>)>,
    pub timestamp: Option<i64>,
}

impl KafkaMessage {
    /// The last value of a repeated key wins, as in `parseKafkaHeaders`.
    pub fn header_map(&self) -> std::collections::HashMap<String, String> {
        let mut map = std::collections::HashMap::new();
        for (key, value) in &self.headers {
            if let Some(value) = value {
                map.insert(key.clone(), String::from_utf8_lossy(value).into_owned());
            }
        }
        map
    }

    pub fn header(&self, name: &str) -> Option<String> {
        self.headers
            .iter()
            .rev()
            .find(|(key, _)| key == name)
            .and_then(|(_, value)| value.as_ref())
            .map(|value| String::from_utf8_lossy(value).into_owned())
    }
}

/// Headers in insertion order. `set` replaces a key in place, as a JS object does.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Headers(pub Vec<(String, String)>);

impl Headers {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn set(&mut self, key: impl Into<String>, value: impl Into<String>) {
        let key = key.into();
        let value = value.into();
        match self.0.iter_mut().find(|(k, _)| *k == key) {
            Some(entry) => entry.1 = value,
            None => self.0.push((key, value)),
        }
    }

    pub fn get(&self, key: &str) -> Option<&str> {
        self.0
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.as_str())
    }

    pub fn remove(&mut self, key: &str) {
        self.0.retain(|(k, _)| k != key);
    }

    pub fn iter(&self) -> impl Iterator<Item = &(String, String)> {
        self.0.iter()
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

impl<K: Into<String>, V: Into<String>> FromIterator<(K, V)> for Headers {
    fn from_iter<I: IntoIterator<Item = (K, V)>>(iter: I) -> Self {
        let mut headers = Headers::new();
        for (k, v) in iter {
            headers.set(k, v);
        }
        headers
    }
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct OutputMessage {
    pub value: Option<Bytes>,
    pub key: Option<Vec<u8>>,
    pub headers: Headers,
}

#[async_trait]
pub trait IngestionOutputs: Send + Sync {
    async fn produce(&self, output: &str, message: OutputMessage) -> anyhow::Result<()>;
    /// Resolves on the ack, as Node's `queueMessages` does.
    async fn queue_messages(
        &self,
        output: &str,
        messages: Vec<OutputMessage>,
    ) -> anyhow::Result<()>;
}

#[derive(Default, Clone)]
pub struct MemoryOutputs {
    inner: Arc<Mutex<MemoryOutputsState>>,
}

#[derive(Default)]
struct MemoryOutputsState {
    produced: Vec<(String, OutputMessage)>,
    fail_outputs: Vec<String>,
}

impl MemoryOutputs {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn produced(&self) -> Vec<(String, OutputMessage)> {
        self.inner.lock().unwrap().produced.clone()
    }

    pub fn produced_to(&self, output: &str) -> Vec<OutputMessage> {
        self.inner
            .lock()
            .unwrap()
            .produced
            .iter()
            .filter(|(o, _)| o == output)
            .map(|(_, m)| m.clone())
            .collect()
    }

    pub fn fail_output(&self, output: &str) {
        self.inner
            .lock()
            .unwrap()
            .fail_outputs
            .push(output.to_string());
    }

    pub fn clear_failures(&self) {
        self.inner.lock().unwrap().fail_outputs.clear();
    }

    fn record(&self, output: &str, messages: Vec<OutputMessage>) -> anyhow::Result<()> {
        let mut state = self.inner.lock().unwrap();
        if state.fail_outputs.iter().any(|o| o == output) {
            anyhow::bail!("produce to {output} failed");
        }
        state
            .produced
            .extend(messages.into_iter().map(|m| (output.to_string(), m)));
        Ok(())
    }
}

#[async_trait]
impl IngestionOutputs for MemoryOutputs {
    async fn produce(&self, output: &str, message: OutputMessage) -> anyhow::Result<()> {
        self.record(output, vec![message])
    }

    async fn queue_messages(
        &self,
        output: &str,
        messages: Vec<OutputMessage>,
    ) -> anyhow::Result<()> {
        self.record(output, messages)
    }
}

pub trait HasMessage {
    fn message(&self) -> &KafkaMessage;
}

pub trait HasTeamId {
    fn team_id(&self) -> i64;
}
