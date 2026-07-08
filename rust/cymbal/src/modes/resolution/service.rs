use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

use crate::stages::resolution::ResolutionStage;
use crate::symbolication::symbol::SymbolResolver;
use std::pin::Pin;

use crate::modes::resolution::load_monitor::LoadMonitor;
use cymbal_proto::cymbal::resolution::v1::cymbal_resolution_server::CymbalResolution;
use cymbal_proto::cymbal::resolution::v1::{
    LoadEvent, ResolveItem, ResolveOutcome, SubscribeRequest,
};

use futures::Stream;
use tokio::sync::mpsc;
use tokio::sync::Semaphore;
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status};
use tracing::info;

pub mod codes;
mod config;
mod resolve;
mod subscribe;

pub use config::ServiceConfig;

use resolve::run_resolve;
use subscribe::{load_event_stream, SubscribeRuntime};

/// Channel buffer for streamed outcomes. Sized to absorb a short backlog while
/// the caller drains; not a queue replacement for backpressure.
const OUTCOME_CHANNEL_BUFFER: usize = 64;

pub struct CymbalResolutionService {
    symbol_resolver: Arc<dyn SymbolResolver>,
    symbol_resolution_limiter: Arc<Semaphore>,
    load_monitor: LoadMonitor,
    service_instance_id: Arc<str>,
    service_config: ServiceConfig,
}

impl CymbalResolutionService {
    pub fn new(
        symbol_resolver: Arc<dyn SymbolResolver>,
        symbol_resolution_limiter: Arc<Semaphore>,
        load_monitor: LoadMonitor,
        service_instance_id: impl Into<Arc<str>>,
        service_config: ServiceConfig,
        draining: Arc<AtomicBool>,
    ) -> Self {
        load_monitor.set_draining(draining.load(Ordering::Relaxed));
        Self {
            symbol_resolver,
            symbol_resolution_limiter,
            load_monitor,
            service_instance_id: service_instance_id.into(),
            service_config,
        }
    }

    fn resolution_stage(&self) -> ResolutionStage {
        ResolutionStage {
            symbol_resolver: self.symbol_resolver.clone(),
            symbol_resolution_limiter: self.symbol_resolution_limiter.clone(),
            // The cymbal-resolution server never enables remote mode itself;
            // it is the server side that cymbal talks to. Local resolution is
            // the only valid path here.
            remote: None,
        }
    }
}

type ResolveStream = Pin<Box<dyn Stream<Item = Result<ResolveOutcome, Status>> + Send>>;
type SubscribeStream = Pin<Box<dyn Stream<Item = Result<LoadEvent, Status>> + Send>>;

#[tonic::async_trait]
impl CymbalResolution for CymbalResolutionService {
    type ResolveStream = ResolveStream;
    type SubscribeStream = SubscribeStream;

    async fn resolve(
        &self,
        request: Request<tonic::Streaming<ResolveItem>>,
    ) -> Result<Response<Self::ResolveStream>, Status> {
        let input = request.into_inner();

        let stage = self.resolution_stage();

        let (tx, rx) = mpsc::channel::<Result<ResolveOutcome, Status>>(OUTCOME_CHANNEL_BUFFER);

        let load_monitor = self.load_monitor.clone();

        tokio::spawn(async move {
            run_resolve(input, stage, tx, load_monitor).await;
        });

        let stream = ReceiverStream::new(rx);
        let boxed: ResolveStream = Box::pin(stream);
        Ok(Response::new(boxed))
    }

    async fn subscribe(
        &self,
        request: Request<SubscribeRequest>,
    ) -> Result<Response<Self::SubscribeStream>, Status> {
        let req = request.into_inner();
        let tick = self.service_config.resolve_tick_interval(req.tick_hint_ms);
        let subscriber_id = if req.subscriber_id.is_empty() {
            "<anonymous>".to_string()
        } else {
            req.subscriber_id.clone()
        };
        info!(
            subscriber = %subscriber_id,
            tick_ms = tick.as_millis() as u64,
            "load event subscription opened",
        );

        let stream = load_event_stream(SubscribeRuntime {
            service_instance_id: self.service_instance_id.clone(),
            load_monitor: self.load_monitor.clone(),
            tick,
            subscriber_id,
        });

        let boxed: SubscribeStream = Box::pin(stream);
        Ok(Response::new(boxed))
    }
}
