use anyhow::{Result, ensure};
use meep_store::{self as store, Connection};
use parking_lot::Mutex;
use serde_json::Value;

/// Durable checkpoints for all watches on a connection.
pub trait StateStore: Send + Sync {
    /// Expire acknowledged webhook deliveries outside the replay window.
    fn maintain(&self) -> Result<()> {
        Ok(())
    }
    /// Loads the last successful batch of observations.
    fn load(&self, connection: &str) -> Result<Option<Value>>;

    /// Commits every watch together. Fail without changes if another poll has
    /// replaced the expected checkpoint while requests were in flight.
    fn commit(&self, connection: &str, expected: Option<&Value>, next: &Value) -> Result<()>;

    /// Whether the host has acknowledged this webhook event. Stores that stage
    /// poll commits must delegate receipt operations directly to durable storage.
    fn webhook_delivered(&self, connection: &str, event: &str) -> Result<bool> {
        Ok(self.load(&receipt_key(connection, event)?)?.is_some())
    }

    /// Idempotently record a successful engine delivery, including concurrent retries.
    fn mark_webhook_delivered(&self, connection: &str, event: &str) -> Result<()> {
        let key = receipt_key(connection, event)?;
        if self.load(&key)?.is_none()
            && let Err(error) = self.commit(&key, None, &Value::Bool(true))
            && self.load(&key)?.is_none()
        {
            return Err(error);
        }
        Ok(())
    }
}

/// Checkpoints stored in the host's meep-store database.
pub struct StoreState(Mutex<Connection>);

const KIND: &str = "connectors/checkpoint/v1";

impl StoreState {
    /// Initializes storage on the supplied database handle.
    pub fn new(db: Connection) -> Result<Self> {
        store::initialize(&db)?;
        Ok(Self(Mutex::new(db)))
    }
}

impl StateStore for StoreState {
    fn maintain(&self) -> Result<()> {
        let prefix = b"\0webhook-receipt/";
        self.0.lock().execute("DELETE FROM records WHERE kind=?1 AND substr(CAST(id AS BLOB),1,?2)=?3 AND updated_ms<unixepoch('now','-30 days')*1000",(KIND,prefix.len() as i64,prefix.as_slice()))?;
        Ok(())
    }
    fn load(&self, connection: &str) -> Result<Option<Value>> {
        store::get(&self.0.lock(), KIND, connection)
    }

    fn commit(&self, connection: &str, expected: Option<&Value>, next: &Value) -> Result<()> {
        store::transaction(&mut self.0.lock(), |db| {
            let current = store::get::<Value>(db, KIND, connection)?;
            ensure!(
                current.as_ref() == expected,
                "concurrent poll on {connection}; retry"
            );
            store::put(db, KIND, connection, next)
        })
    }
}

fn receipt_key(connection: &str, event: &str) -> Result<String> {
    Ok(format!(
        "\0webhook-receipt/{}",
        crate::source_key((connection, event))?
    ))
}
