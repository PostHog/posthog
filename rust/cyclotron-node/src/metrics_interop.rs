use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, RwLock, Weak,
};

use ahash::AHashMap;
use metrics::{
    Counter, CounterFn, Gauge, GaugeFn, Histogram, Key, KeyName, Metadata, Recorder, SharedString,
    Unit,
};

pub struct NodeRegistry {
    inner: NodeRegistryInner,
}

// So many Arc's you should call me noah
impl Recorder for NodeRegistry {
    fn describe_counter(&self, _key: KeyName, _unit: Option<Unit>, _description: SharedString) {}

    fn describe_gauge(&self, _key: KeyName, _unit: Option<Unit>, _description: SharedString) {}

    fn describe_histogram(&self, _key: KeyName, _unit: Option<Unit>, _description: SharedString) {}

    fn register_counter(&self, key: &Key, _metadata: &Metadata<'_>) -> Counter {
        let counter = Arc::new(AtomicU64::new(0));
        self.inner
            .counters
            .write()
            .unwrap()
            .insert(key.clone(), counter.clone());

        let counter_fn = Arc::new(CounterFnImpl(Arc::downgrade(&counter)));
        Counter::from_arc(counter_fn)
    }

    fn register_gauge(&self, key: &Key, _metadata: &Metadata<'_>) -> Gauge {
        let gauge = Arc::new(AtomicF64::new(0.0));
        self.inner
            .gauges
            .write()
            .unwrap()
            .insert(key.clone(), gauge.clone());

        let gauge_fn = Arc::new(GaugeFnImpl(Arc::downgrade(&gauge)));
        Gauge::from_arc(gauge_fn)
    }

    fn register_histogram(&self, _key: &Key, _metadata: &Metadata<'_>) -> metrics::Histogram {
        // This doesn't use `todo()` or `unimplemented!()` because, because in the context
        // we're better off dropping rust-side metrics than panicking a node process just
        // because I forgot to implement this.
        Histogram::noop()
    }
}

struct NodeRegistryInner {
    pub counters: RwLock<AHashMap<Key, Arc<AtomicU64>>>,
    pub gauges: RwLock<AHashMap<Key, Arc<AtomicF64>>>,
}

struct CounterFnImpl(Weak<AtomicU64>);
impl CounterFn for CounterFnImpl {
    fn increment(&self, value: u64) {
        if let Some(counter) = self.0.upgrade() {
            counter.fetch_add(value, Ordering::Relaxed);
        }
    }

    fn absolute(&self, value: u64) {
        if let Some(counter) = self.0.upgrade() {
            counter.store(value, Ordering::Relaxed);
        }
    }
}

struct GaugeFnImpl(Weak<AtomicF64>);
impl GaugeFn for GaugeFnImpl {
    fn increment(&self, value: f64) {
        if let Some(gauge) = self.0.upgrade() {
            gauge.add(value, Ordering::Relaxed, Ordering::Relaxed);
        }
    }

    fn decrement(&self, value: f64) {
        if let Some(gauge) = self.0.upgrade() {
            gauge.add(-value, Ordering::Relaxed, Ordering::Relaxed);
        }
    }

    fn set(&self, value: f64) {
        if let Some(gauge) = self.0.upgrade() {
            gauge.store(value, Ordering::Relaxed);
        }
    }
}

// Rust doesn't have one of these for very sane reasons that we don't care about (unlike ints,
// most platforms don't have native atomic operations for floats, like add or sub).
#[derive(Debug)]
pub struct AtomicF64 {
    storage: AtomicU64,
}

impl AtomicF64 {
    pub fn new(value: f64) -> Self {
        Self {
            storage: AtomicU64::new(value.to_bits()),
        }
    }

    pub fn store(&self, value: f64, ordering: Ordering) {
        self.storage.store(value.to_bits(), ordering)
    }

    pub fn load(&self, ordering: Ordering) -> f64 {
        f64::from_bits(self.storage.load(ordering))
    }

    pub fn add(&self, value: f64, success: Ordering, failure: Ordering) -> f64 {
        // Note - we could try to fetch the existing value preemptively here, but
        // since we have to assume it's changed between the fetch and the compare_exchange,
        // we might as well just go straight into the loop. Space for optimisation here
        let mut current = 0f64;
        loop {
            let new = current + value;
            match self
                .storage
                .compare_exchange(current.to_bits(), new.to_bits(), success, failure)
            {
                Ok(_) => return new,
                Err(actual) => current = f64::from_bits(actual),
            }
        }
    }
}
