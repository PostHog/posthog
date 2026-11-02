//! Port of `steps.ts` and `ChunkProcessingStep` from `base-chunk-pipeline.ts`. Node reads a step's
//! name from the function's `.name`, and Rust closures have none, so a step carries its name.

use std::future::Future;
use std::sync::Arc;

use futures::future::BoxFuture;
use futures::FutureExt;

use crate::results::PipelineResult;

pub type StepFuture<U> = BoxFuture<'static, anyhow::Result<PipelineResult<U>>>;
pub type ChunkStepFuture<U> = BoxFuture<'static, anyhow::Result<Vec<PipelineResult<U>>>>;

/// An `Err` is the Node `throw`: it propagates and is not converted into a DLQ.
pub struct ProcessingStep<T, U> {
    name: Arc<str>,
    f: Arc<dyn Fn(T) -> StepFuture<U> + Send + Sync>,
}

impl<T, U> Clone for ProcessingStep<T, U> {
    fn clone(&self) -> Self {
        Self {
            name: self.name.clone(),
            f: self.f.clone(),
        }
    }
}

impl<T: 'static, U: 'static> ProcessingStep<T, U> {
    pub fn new<F, Fut>(name: &str, f: F) -> Self
    where
        F: Fn(T) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = anyhow::Result<PipelineResult<U>>> + Send + 'static,
    {
        Self {
            name: Arc::from(name),
            f: Arc::new(move |value| f(value).boxed()),
        }
    }

    pub fn sync<F>(name: &str, f: F) -> Self
    where
        F: Fn(T) -> anyhow::Result<PipelineResult<U>> + Send + Sync + 'static,
        U: Send,
    {
        Self {
            name: Arc::from(name),
            f: Arc::new(move |value| futures::future::ready(f(value)).boxed()),
        }
    }

    pub fn name(&self) -> &Arc<str> {
        &self.name
    }

    pub fn call(&self, value: T) -> StepFuture<U> {
        (self.f)(value)
    }

    pub fn renamed(mut self, name: &str) -> Self {
        self.name = Arc::from(name);
        self
    }
}

pub struct ChunkProcessingStep<T, U> {
    name: Arc<str>,
    f: Arc<dyn Fn(Vec<T>) -> ChunkStepFuture<U> + Send + Sync>,
}

impl<T, U> Clone for ChunkProcessingStep<T, U> {
    fn clone(&self) -> Self {
        Self {
            name: self.name.clone(),
            f: self.f.clone(),
        }
    }
}

impl<T: 'static, U: 'static> ChunkProcessingStep<T, U> {
    pub fn new<F, Fut>(name: &str, f: F) -> Self
    where
        F: Fn(Vec<T>) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = anyhow::Result<Vec<PipelineResult<U>>>> + Send + 'static,
    {
        Self {
            name: Arc::from(name),
            f: Arc::new(move |values| f(values).boxed()),
        }
    }

    pub fn sync<F>(name: &str, f: F) -> Self
    where
        F: Fn(Vec<T>) -> anyhow::Result<Vec<PipelineResult<U>>> + Send + Sync + 'static,
        U: Send,
    {
        Self {
            name: Arc::from(name),
            f: Arc::new(move |values| futures::future::ready(f(values)).boxed()),
        }
    }

    pub fn name(&self) -> &Arc<str> {
        &self.name
    }

    pub fn call(&self, values: Vec<T>) -> ChunkStepFuture<U> {
        (self.f)(values)
    }
}

impl<T: Send + 'static, U: Send + 'static> ChunkProcessingStep<T, U> {
    /// Same as the `perMessage` helper in the Node metrics pipeline.
    pub fn per_item(step: ProcessingStep<T, U>) -> Self {
        crate::per_element::per_element(step, None)
    }
}

pub fn step<T, U, F, Fut>(name: &str, f: F) -> ProcessingStep<T, U>
where
    T: 'static,
    U: 'static,
    F: Fn(T) -> Fut + Send + Sync + 'static,
    Fut: Future<Output = anyhow::Result<PipelineResult<U>>> + Send + 'static,
{
    ProcessingStep::new(name, f)
}

pub fn chunk_step<T, U, F, Fut>(name: &str, f: F) -> ChunkProcessingStep<T, U>
where
    T: 'static,
    U: 'static,
    F: Fn(Vec<T>) -> Fut + Send + Sync + 'static,
    Fut: Future<Output = anyhow::Result<Vec<PipelineResult<U>>>> + Send + 'static,
{
    ChunkProcessingStep::new(name, f)
}
