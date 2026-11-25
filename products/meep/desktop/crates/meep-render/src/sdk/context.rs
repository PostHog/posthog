//! Native script lifecycle and requests to the embedding host.
use serde_json::Value;
use std::sync::Arc;

use crate::HostError;

/// Services granted to one mounted script, bound by the embedding application.
#[async_trait::async_trait]
pub trait ViewHost: Send + Sync {
    async fn request(&self, method: &str, params: Value) -> Result<Value, HostError>;
    fn saves_checkpoints(&self) -> bool {
        false
    }
    /// Only the native save coordinator can request a replacement writer lease.
    async fn remount(&self, _writer: Option<String>) -> Result<Value, String> {
        Err("This host does not manage writer leases".into())
    }
}

#[derive(Clone)]
pub struct ViewContext {
    pub view_id: String,
    pub initial_state: Value,
    pub(crate) host: Arc<dyn ViewHost>,
    pub runtime: Arc<tokio::runtime::Runtime>,
    pub revision: String,
    activation: Arc<Activation>,
    mount_error: Arc<std::sync::Mutex<Option<String>>>,
    sequence: Arc<std::sync::atomic::AtomicU64>,
    writer: Arc<std::sync::Mutex<Option<String>>>,
    background_request: Arc<std::sync::Mutex<Option<String>>>,
}
struct Activation {
    state: std::sync::atomic::AtomicU8,
    changed: tokio::sync::Notify,
}
impl ViewContext {
    pub fn new(
        view_id: String,
        initial_state: Value,
        host: Arc<dyn ViewHost>,
        runtime: Arc<tokio::runtime::Runtime>,
        revision: String,
        active: bool,
    ) -> Self {
        Self {
            view_id,
            initial_state,
            host,
            runtime,
            revision,
            sequence: Arc::new(std::sync::atomic::AtomicU64::new(0)),
            writer: Arc::default(),
            mount_error: Arc::default(),
            background_request: Arc::default(),
            activation: Arc::new(Activation {
                state: std::sync::atomic::AtomicU8::new(if active { 1 } else { 0 }),
                changed: tokio::sync::Notify::new(),
            }),
        }
    }
    pub fn sequence(&self) -> u64 {
        self.sequence.load(std::sync::atomic::Ordering::Acquire)
    }
    pub fn set_sequence(&self, sequence: u64) {
        self.sequence
            .store(sequence, std::sync::atomic::Ordering::Release);
    }
    pub fn writer(&self) -> Option<String> {
        self.writer.lock().unwrap().clone()
    }
    pub fn set_writer(&self, writer: String) {
        *self.writer.lock().unwrap() = Some(writer);
    }
    pub fn is_active(&self) -> bool {
        self.activation
            .state
            .load(std::sync::atomic::Ordering::Acquire)
            == 1
    }
    /// Local interaction can continue while broker ownership is pending.
    pub fn is_retired(&self) -> bool {
        self.activation
            .state
            .load(std::sync::atomic::Ordering::Acquire)
            == 2
    }
    pub fn refuse_mount(&self, error: String) {
        *self.mount_error.lock().unwrap() = Some(error);
        self.suspend();
    }
    pub fn mount_error(&self) -> Option<String> {
        self.mount_error.lock().unwrap().clone()
    }
    pub fn suspend(&self) {
        self.activation
            .state
            .store(0, std::sync::atomic::Ordering::Release);
    }
    pub fn activate(&self) {
        *self.mount_error.lock().unwrap() = None;
        self.activation
            .state
            .store(1, std::sync::atomic::Ordering::Release);
        self.activation.changed.notify_waiters();
    }
    pub fn retire(&self) {
        self.activation
            .state
            .store(2, std::sync::atomic::Ordering::Release);
        self.activation.changed.notify_waiters();
    }

    pub fn background_request(&self) -> Option<String> {
        self.background_request.lock().unwrap().clone()
    }
    pub fn set_background_request(&self, request: Option<String>) {
        *self.background_request.lock().unwrap() = request;
    }
    pub fn request(
        &self,
        method: &str,
        params: Value,
    ) -> async_channel::Receiver<Result<Value, String>> {
        self.request_inner(method, params, None)
    }
    /// Native workflow cancellation drops the connection to cancellable host
    /// calls. Ordinary fire-and-forget state saves retain their usual behavior.
    pub fn request_cancellable(
        &self,
        method: &str,
        params: Value,
        cancelled: async_channel::Receiver<()>,
    ) -> async_channel::Receiver<Result<Value, HostError>> {
        self.request_inner(method, params, Some(cancelled))
    }
    fn request_inner<E: From<HostError> + std::fmt::Display + Send + 'static>(
        &self,
        method: &str,
        mut params: Value,
        cancelled: Option<async_channel::Receiver<()>>,
    ) -> async_channel::Receiver<Result<Value, E>> {
        if let (Some(group), Some(params)) = (
            self.background_request.lock().unwrap().as_ref(),
            params.as_object_mut(),
        ) {
            params.insert("_background_request".into(), serde_json::json!(group));
        }
        let (tx, rx) = async_channel::bounded(1);
        let host = self.host.clone();
        let method = method.to_owned();
        let activation = self.activation.clone();
        self.runtime.spawn(async move {
            let work = async {
                let ready = loop {
                    let changed = activation.changed.notified();
                    match activation.state.load(std::sync::atomic::Ordering::Acquire) {
                        1 => break true,
                        2 => break false,
                        _ => changed.await,
                    }
                };
                if !ready {
                    return Err("This view generation was replaced".into());
                }
                host.request(&method, params).await
            };
            let value = if let Some(cancelled) = cancelled {
                tokio::select! {
                    biased;
                    _ = cancelled.recv() => Err("Workflow cancelled".into()),
                    result = work => result,
                }
            } else {
                work.await
            };
            if let Err(async_channel::SendError(Err(error))) = tx.send(value.map_err(E::from)).await
            {
                eprintln!(
                    "The view request {method} failed after its caller disconnected: {error}"
                );
            }
        });
        rx
    }
}
