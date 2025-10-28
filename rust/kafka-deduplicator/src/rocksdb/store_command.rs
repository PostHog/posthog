use anyhow::Result;
use std::path::PathBuf;
use tokio::sync::oneshot;

/// Commands that can be sent to the RocksDB store worker thread
pub enum StoreCommand {
    Get {
        cf_name: String,
        key: Vec<u8>,
        response: oneshot::Sender<Result<Option<Vec<u8>>>>,
    },
    MultiGet {
        cf_name: String,
        keys: Vec<Vec<u8>>,
        response: oneshot::Sender<Result<Vec<Option<Vec<u8>>>>>,
    },
    Put {
        cf_name: String,
        key: Vec<u8>,
        value: Vec<u8>,
        response: oneshot::Sender<Result<()>>,
    },
    PutBatch {
        cf_name: String,
        entries: Vec<(Vec<u8>, Vec<u8>)>,
        response: oneshot::Sender<Result<()>>,
    },
    Delete {
        cf_name: String,
        key: Vec<u8>,
        response: oneshot::Sender<Result<()>>,
    },
    DeleteRange {
        cf_name: String,
        start: Vec<u8>,
        end: Vec<u8>,
        response: oneshot::Sender<Result<()>>,
    },
    FlushCf {
        cf_name: String,
        response: oneshot::Sender<Result<()>>,
    },
    FlushAllCf {
        response: oneshot::Sender<Result<()>>,
    },
    FlushWal {
        sync: bool,
        response: oneshot::Sender<Result<()>>,
    },
    GetDbSize {
        cf_name: String,
        response: oneshot::Sender<Result<u64>>,
    },
    UpdateDbMetrics {
        cf_name: String,
        response: oneshot::Sender<Result<()>>,
    },
    CreateCheckpoint {
        path: PathBuf,
        response: oneshot::Sender<Result<()>>,
    },
    GetSstFileNames {
        cf_name: String,
        response: oneshot::Sender<Result<Vec<String>>>,
    },
    LatestSequenceNumber {
        response: oneshot::Sender<u64>,
    },
    Shutdown {
        response: oneshot::Sender<()>,
    },
}
