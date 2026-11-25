//! Synchronous script entries. Platform engines use the same prelude and JSON ABI.
use serde_json::Value;
pub trait ScriptEngine {
    fn render(&self) -> Result<Value, String>;
    fn row(&self, function: u32, index: usize) -> Result<Value, String>;
    fn cell(&self, function: u32, row: &Value) -> Result<Value, String>;
    fn invoke(&self, handler: u32, argument: &Value) -> Result<(), String>;
    fn key(&self, name: &str) -> Result<bool, String>;
    fn init(&self) -> Result<(), String>;
    fn settle(&self, id: u32, result: Result<Value, String>) -> Result<(), String>;
    fn fire(&self, timer: u64) -> Result<(), String>;
}

#[derive(Default)]
pub struct HostQueue {
    pub dirty: bool,
    bytes: usize,
    /// Broker requests: (promise id, method, params).
    pub requests: Vec<(u32, String, Value)>,
    /// Window-local effects: open_url, copy, focus, timer.
    pub local: Vec<(String, Value)>,
}

impl HostQueue {
    pub fn reserve(&mut self, bytes: usize) -> bool {
        if bytes > 128 * 1024
            || self.bytes.saturating_add(bytes) > 512 * 1024
            || self.requests.len() + self.local.len() >= 128
        {
            return false;
        }
        self.bytes += bytes;
        true
    }
}
