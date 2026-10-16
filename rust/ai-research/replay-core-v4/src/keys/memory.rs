//! An in-memory key table for tests. DynamoDB is the boundary, so tests replace it here.

use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

use async_trait::async_trait;

use super::rows::{Row, TableKey};
use super::table::{KeyTable, PutOutcome, TableError};

#[derive(Default)]
pub struct MemoryTable {
    pub rows: Mutex<HashMap<TableKey, Row>>,
    pub reads: AtomicUsize,
}

impl MemoryTable {
    /// Stores a row as another writer would, behind this process's back.
    pub fn store(&self, key: TableKey, row: Row) {
        self.rows.lock().unwrap().insert(key, row);
    }
}

#[async_trait]
impl KeyTable for MemoryTable {
    async fn batch_get(&self, keys: &[TableKey]) -> Result<HashMap<TableKey, Row>, TableError> {
        self.reads.fetch_add(1, Ordering::SeqCst);
        let rows = self.rows.lock().unwrap();
        Ok(keys
            .iter()
            .filter_map(|k| rows.get(k).map(|r| (k.clone(), r.clone())))
            .collect())
    }

    async fn put_if_absent(&self, key: &TableKey, row: &Row) -> Result<PutOutcome, TableError> {
        let mut rows = self.rows.lock().unwrap();
        match rows.get(key) {
            Some(existing) => Ok(PutOutcome::Existing(existing.clone())),
            None => {
                rows.insert(key.clone(), row.clone());
                Ok(PutOutcome::Stored)
            }
        }
    }
}
