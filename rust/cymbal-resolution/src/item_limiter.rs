use std::sync::Arc;

use tokio::sync::{AcquireError, OwnedSemaphorePermit, Semaphore, TryAcquireError};

/// Process-wide admission gate for exception item processing.
#[derive(Clone, Debug)]
pub struct ItemLimiter {
    semaphore: Arc<Semaphore>,
    max_permits: usize,
}

impl ItemLimiter {
    pub fn new(max_permits: usize) -> Self {
        let max_permits = max_permits.max(1);
        Self {
            semaphore: Arc::new(Semaphore::new(max_permits)),
            max_permits,
        }
    }

    pub fn from_semaphore(semaphore: Arc<Semaphore>, max_permits: usize) -> Self {
        Self {
            semaphore,
            max_permits: max_permits.max(1),
        }
    }

    pub async fn acquire_owned(&self) -> Result<OwnedSemaphorePermit, AcquireError> {
        self.semaphore.clone().acquire_owned().await
    }

    pub fn try_acquire_owned(&self) -> Result<OwnedSemaphorePermit, TryAcquireError> {
        self.semaphore.clone().try_acquire_owned()
    }

    pub fn available_permits(&self) -> usize {
        self.semaphore.available_permits()
    }

    pub fn max_permits(&self) -> usize {
        self.max_permits
    }

    pub fn close(&self) {
        self.semaphore.close();
    }
}

#[cfg(test)]
mod tests {
    use super::ItemLimiter;

    #[tokio::test]
    async fn max_permits_remains_the_configured_capacity() {
        let limiter = ItemLimiter::new(3);
        let _permit = limiter.acquire_owned().await.unwrap();

        assert_eq!(limiter.max_permits(), 3);
        assert_eq!(limiter.available_permits(), 2);
    }
}
