//! KMS wraps every team month key. Unwrapped keys are cached, so a busy team costs one KMS call per cache lifetime per
//! process, not one per flush.

use std::num::NonZeroU32;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use aws_sdk_kms::error::DisplayErrorContext;
use aws_sdk_kms::primitives::Blob;
use aws_sdk_kms::types::DataKeySpec;
use governor::clock::DefaultClock;
use governor::state::{InMemoryState, NotKeyed};
use governor::{Quota, RateLimiter};
use moka::future::Cache;
use tokio::sync::Semaphore;

use crate::seal::WrappingContext;

#[derive(Debug, Clone, thiserror::Error)]
pub enum KmsError {
    #[error("KMS request failed: {0}")]
    Request(String),
    #[error("KMS request timed out")]
    Timeout,
    /// KMS refused this one blob, so retrying cannot help, and other keys still unwrap.
    #[error("KMS refused the wrapped key: {0}")]
    Rejected(String),
    #[error("KMS returned a key that is not 32 bytes")]
    InvalidKey,
}

/// A fresh team month key: the plaintext to seal with, and the KMS blob to store.
#[derive(Clone)]
pub struct DataKey {
    pub plaintext: [u8; 32],
    pub wrapped: Vec<u8>,
}

/// The two KMS calls the key store makes. Tests replace KMS at this boundary.
#[async_trait]
pub trait KeyWrapper: Send + Sync {
    async fn generate(&self, context: &WrappingContext) -> Result<DataKey, KmsError>;
    async fn unwrap(&self, context: &WrappingContext, wrapped: &[u8])
        -> Result<[u8; 32], KmsError>;
}

/// Limits that match the v3 mirror: KMS throttles a whole account, so one lane must not take all of it.
#[derive(Debug, Clone)]
pub struct KmsLimits {
    pub requests_per_second: NonZeroU32,
    pub max_in_flight: usize,
    pub timeout: Duration,
}

impl Default for KmsLimits {
    fn default() -> Self {
        Self {
            requests_per_second: NonZeroU32::new(150).expect("nonzero"),
            max_in_flight: 8,
            timeout: Duration::from_secs(5),
        }
    }
}

pub struct AwsKms {
    client: aws_sdk_kms::Client,
    key_id: String,
    rate: RateLimiter<NotKeyed, InMemoryState, DefaultClock>,
    in_flight: Semaphore,
    timeout: Duration,
}

impl AwsKms {
    pub fn new(client: aws_sdk_kms::Client, key_id: String, limits: KmsLimits) -> Self {
        Self {
            client,
            key_id,
            rate: RateLimiter::direct(Quota::per_second(limits.requests_per_second)),
            in_flight: Semaphore::new(limits.max_in_flight),
            timeout: limits.timeout,
        }
    }

    async fn call<T, F>(&self, request: F) -> Result<T, KmsError>
    where
        F: std::future::Future<Output = Result<T, KmsError>>,
    {
        let _permit = self
            .in_flight
            .acquire()
            .await
            .map_err(|e| KmsError::Request(e.to_string()))?;
        self.rate.until_ready().await;
        tokio::time::timeout(self.timeout, request)
            .await
            .map_err(|_| KmsError::Timeout)?
    }
}

fn plaintext(bytes: Option<&Blob>) -> Result<[u8; 32], KmsError> {
    bytes
        .map(|blob| blob.as_ref())
        .and_then(|b| b.try_into().ok())
        .ok_or(KmsError::InvalidKey)
}

#[async_trait]
impl KeyWrapper for AwsKms {
    async fn generate(&self, context: &WrappingContext) -> Result<DataKey, KmsError> {
        let mut request = self
            .client
            .generate_data_key()
            .key_id(&self.key_id)
            .key_spec(DataKeySpec::Aes256);
        for (name, value) in context.entries() {
            request = request.encryption_context(name, value);
        }
        let output = self
            .call(async {
                request
                    .send()
                    .await
                    .map_err(|e| KmsError::Request(DisplayErrorContext(&e).to_string()))
            })
            .await?;
        let wrapped = output
            .ciphertext_blob()
            .map(|blob| blob.as_ref().to_vec())
            .filter(|b| !b.is_empty());
        Ok(DataKey {
            plaintext: plaintext(output.plaintext())?,
            wrapped: wrapped.ok_or(KmsError::InvalidKey)?,
        })
    }

    async fn unwrap(
        &self,
        context: &WrappingContext,
        wrapped: &[u8],
    ) -> Result<[u8; 32], KmsError> {
        let mut request = self
            .client
            .decrypt()
            .key_id(&self.key_id)
            .ciphertext_blob(Blob::new(wrapped));
        for (name, value) in context.entries() {
            request = request.encryption_context(name, value);
        }
        let output = self
            .call(async {
                request.send().await.map_err(|e| {
                    // A blob that is corrupt, or that does not match its context, gets one of these. An access
                    // denial or a disabled key stops every unwrap, so it stays a failed request.
                    let rejected = e.as_service_error().is_some_and(|e| {
                        e.is_invalid_ciphertext_exception() || e.is_incorrect_key_exception()
                    });
                    if rejected {
                        KmsError::Rejected(DisplayErrorContext(&e).to_string())
                    } else {
                        KmsError::Request(DisplayErrorContext(&e).to_string())
                    }
                })
            })
            .await?;
        plaintext(output.plaintext())
    }
}

/// The KMS encryption context and the wrapped blob, which together name one unwrapped key.
type UnwrapId = (Vec<(&'static str, String)>, Vec<u8>);

/// Caches unwrapped keys. Concurrent unwraps of one key share a single KMS call.
pub struct CachedKms<W> {
    inner: W,
    cache: Cache<UnwrapId, [u8; 32]>,
}

impl<W: KeyWrapper> CachedKms<W> {
    pub fn new(inner: W, max_keys: u64, lifetime: Duration) -> Self {
        Self {
            inner,
            cache: Cache::builder()
                .max_capacity(max_keys)
                .time_to_live(lifetime)
                .build(),
        }
    }

    /// Records a key this process generated and stored, so reading it back costs no KMS call.
    pub async fn remember(&self, context: &WrappingContext, key: &DataKey) {
        self.cache
            .insert((context.entries(), key.wrapped.clone()), key.plaintext)
            .await;
    }
}

#[async_trait]
impl<W: KeyWrapper> KeyWrapper for CachedKms<W> {
    async fn generate(&self, context: &WrappingContext) -> Result<DataKey, KmsError> {
        self.inner.generate(context).await
    }

    async fn unwrap(
        &self,
        context: &WrappingContext,
        wrapped: &[u8],
    ) -> Result<[u8; 32], KmsError> {
        self.cache
            .try_get_with(
                (context.entries(), wrapped.to_vec()),
                self.inner.unwrap(context, wrapped),
            )
            .await
            .map_err(|e: Arc<KmsError>| (*e).clone())
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    use tokio::sync::Notify;

    use super::*;

    /// Holds every unwrap until released, so the test controls when KMS answers.
    struct HeldKms {
        calls: AtomicUsize,
        release: Notify,
        fail_first: bool,
    }

    #[async_trait]
    impl KeyWrapper for HeldKms {
        async fn generate(&self, _: &WrappingContext) -> Result<DataKey, KmsError> {
            unreachable!("the cache never generates")
        }

        async fn unwrap(&self, _: &WrappingContext, _: &[u8]) -> Result<[u8; 32], KmsError> {
            let call = self.calls.fetch_add(1, Ordering::SeqCst);
            self.release.notified().await;
            if self.fail_first && call == 0 {
                return Err(KmsError::Timeout);
            }
            Ok([7; 32])
        }
    }

    fn context() -> WrappingContext {
        WrappingContext {
            team_id: 7,
            key_month: "2026-10".to_owned(),
            session_id: None,
        }
    }

    #[tokio::test]
    async fn concurrent_unwraps_of_one_key_make_one_kms_call() {
        let kms = Arc::new(CachedKms::new(
            HeldKms {
                calls: AtomicUsize::new(0),
                release: Notify::new(),
                fail_first: false,
            },
            10,
            Duration::from_secs(60),
        ));
        let waiters: Vec<_> = (0..8)
            .map(|_| {
                let kms = kms.clone();
                tokio::spawn(async move { kms.unwrap(&context(), b"wrapped").await })
            })
            .collect();
        while kms.inner.calls.load(Ordering::SeqCst) == 0 {
            tokio::task::yield_now().await;
        }
        kms.inner.release.notify_one();
        for waiter in waiters {
            assert_eq!(waiter.await.unwrap().unwrap(), [7; 32]);
        }
        assert_eq!(kms.inner.calls.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn a_failed_unwrap_is_not_cached() {
        let kms = Arc::new(CachedKms::new(
            HeldKms {
                calls: AtomicUsize::new(0),
                release: Notify::new(),
                fail_first: true,
            },
            10,
            Duration::from_secs(60),
        ));
        for expected_ok in [false, true] {
            let call = {
                let kms = kms.clone();
                tokio::spawn(async move { kms.unwrap(&context(), b"wrapped").await })
            };
            let calls_before = if expected_ok { 1 } else { 0 };
            while kms.inner.calls.load(Ordering::SeqCst) == calls_before {
                tokio::task::yield_now().await;
            }
            kms.inner.release.notify_one();
            assert_eq!(call.await.unwrap().is_ok(), expected_ok);
        }
    }
}
