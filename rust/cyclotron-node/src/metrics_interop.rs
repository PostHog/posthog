use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, RwLock,
};

use ahash::{AHashMap, HashMap};
use metrics::{
    Counter, CounterFn, Gauge, GaugeFn, HistogramFn, Key, KeyName, Metadata, Recorder,
    SharedString, Unit,
};
use neon::types::Finalize;
use serde::{Deserialize, Serialize};

// ----------------- Interop metrics recorder -----------------
pub struct NodeInteropMetricsRecorder {
    handle: RecorderHandle,

    // We also add a set of default labels to all reported metrics
    default_labels: HashMap<String, String>,
}

#[derive(Clone, Default)]
struct RecorderHandle {
    inner: Arc<RecorderInner>,
}

#[derive(Default)]
struct RecorderInner {
    // Guages and counters are both just atomic values, so they're fairly straightforward
    counters: RwLock<AHashMap<Key, Arc<CounterImpl>>>,
    gauges: RwLock<AHashMap<Key, Arc<GaugeImpl>>>,

    // Histograms are more complicated - we use an atomic bucket to allow lock-free recording
    // and then return all the observations in the report, so whatever is consuming the report
    // can do it's own aggregation. This is roughly how the prometheus recorder works too,
    // except of course it also tracks the aggregated histogram values, and we don't here, because
    // the node side is in charge of that.
    histogram_observations: RwLock<AHashMap<Key, Arc<HistogramImpl>>>,
}

#[derive(Debug, Deserialize)]
pub struct RecorderConfig {
    #[serde(alias = "defaultLabels")]
    default_labels: HashMap<String, String>,
}

impl NodeInteropMetricsRecorder {
    pub fn new() -> Self {
        Self {
            handle: Default::default(),
            default_labels: Default::default(),
        }
    }

    pub fn init(config: RecorderConfig) -> Self {
        let mut new = Self::new();
        new.default_labels = config.default_labels;
        new
    }

    pub fn register(&self) -> Result<(), ()> {
        metrics::set_global_recorder(self.handle.clone()).map_err(|_| ())
    }

    pub fn get_report(&self) -> MetricsReport {
        let mut measurements = vec![];

        let counters = self.handle.inner.counters.read().unwrap();
        for (key, counter) in counters.iter() {
            let name = key.name().to_string();
            let labels = self.get_labels(key);
            let value = MeasurementValue::Counter(counter.0.load(Ordering::Relaxed));
            measurements.push(Measurement {
                name,
                labels,
                value,
            });
        }
        drop(counters);

        let gauges = self.handle.inner.gauges.read().unwrap();
        for (key, gauge) in gauges.iter() {
            let name = key.name().to_string();
            let labels = self.get_labels(key);
            let value = MeasurementValue::Gauge(gauge.0.load(Ordering::Relaxed));
            measurements.push(Measurement {
                name,
                labels,
                value,
            });
        }
        drop(gauges);

        let buckets = self.handle.inner.histogram_observations.read().unwrap();
        for (key, bucket) in buckets.iter() {
            let mut observations = Vec::with_capacity(500);
            let name = key.name().to_string();
            let labels = self.get_labels(key);

            bucket.0.clear_with(|chunk| {
                observations.extend(chunk.iter());
            });

            let value = MeasurementValue::Histogram(observations);
            measurements.push(Measurement {
                name,
                labels,
                value,
            });
        }
        drop(buckets);

        MetricsReport { measurements }
    }

    // Produce a label set for a given key, including any default labels
    fn get_labels(&self, key: &Key) -> HashMap<String, String> {
        key.labels()
            .map(|l| (l.key().to_string(), l.value().to_string()))
            .chain(
                self.default_labels
                    .iter()
                    .map(|(k, v)| (k.to_string(), v.to_string())),
            )
            .collect()
    }
}

#[derive(Debug, Serialize)]
pub struct MetricsReport {
    pub measurements: Vec<Measurement>,
}

#[derive(Debug, Serialize)]
pub struct Measurement {
    pub name: String,
    pub labels: HashMap<String, String>,
    #[serde(flatten)]
    pub value: MeasurementValue,
}

#[derive(Debug, Serialize)]
#[serde(tag = "type", content = "value")]
pub enum MeasurementValue {
    #[serde(rename = "counter")]
    Counter(u64),
    #[serde(rename = "gauge")]
    Gauge(f64),
    #[serde(rename = "histogram")]
    Histogram(Vec<f64>),
}

// ----------------- Metrics recorder impl -----------------
// Extremely simple, ignores metadata, and doesn't support describes (so doesn't support setting units or descriptions), at least for now
impl Recorder for RecorderHandle {
    fn describe_counter(&self, _key: KeyName, _unit: Option<Unit>, _description: SharedString) {}

    fn describe_gauge(&self, _key: KeyName, _unit: Option<Unit>, _description: SharedString) {}

    fn describe_histogram(&self, _key: KeyName, _unit: Option<Unit>, _description: SharedString) {}

    fn register_counter(&self, key: &Key, _metadata: &Metadata<'_>) -> Counter {
        if let Some(counter) = self.inner.counters.read().unwrap().get(key) {
            return Counter::from_arc(counter.clone());
        }

        let mut counters = self.inner.counters.write().unwrap();
        if let Some(counter) = counters.get(key) {
            return Counter::from_arc(counter.clone());
        }
        let counter = Arc::new(CounterImpl(AtomicU64::new(0)));
        counters.insert(key.clone(), counter.clone());
        Counter::from_arc(counter)
    }

    fn register_gauge(&self, key: &Key, _metadata: &Metadata<'_>) -> Gauge {
        if let Some(gauge) = self.inner.gauges.read().unwrap().get(key) {
            return Gauge::from_arc(gauge.clone());
        }

        let mut gauges = self.inner.gauges.write().unwrap();
        if let Some(gauge) = gauges.get(key) {
            return Gauge::from_arc(gauge.clone());
        }
        let gauge = Arc::new(GaugeImpl(AtomicF64::new(0.0)));
        gauges.insert(key.clone(), gauge.clone());
        Gauge::from_arc(gauge)
    }

    fn register_histogram(&self, key: &Key, _metadata: &Metadata<'_>) -> metrics::Histogram {
        if let Some(bucket) = self.inner.histogram_observations.read().unwrap().get(key) {
            return metrics::Histogram::from_arc(bucket.clone());
        }

        let mut buckets = self.inner.histogram_observations.write().unwrap();
        if let Some(bucket) = buckets.get(key) {
            return metrics::Histogram::from_arc(bucket.clone());
        }
        let hist = Arc::new(HistogramImpl(Default::default()));
        buckets.insert(key.clone(), hist.clone());
        metrics::Histogram::from_arc(hist)
    }
}

// ----------------- Metrics function impls -----------------
// This are mostly very simple wrappers around a Weak<T>, for whatever T is relevant for the
// type of metric
struct CounterImpl(AtomicU64);
impl CounterFn for CounterImpl {
    fn increment(&self, value: u64) {
        self.0.fetch_add(value, Ordering::Relaxed);
    }

    fn absolute(&self, value: u64) {
        self.0.store(value, Ordering::Relaxed);
    }
}

struct GaugeImpl(AtomicF64);
impl GaugeFn for GaugeImpl {
    fn increment(&self, value: f64) {
        self.0.add(value, Ordering::Relaxed, Ordering::Relaxed);
    }

    fn decrement(&self, value: f64) {
        self.0.add(-value, Ordering::Relaxed, Ordering::Relaxed);
    }

    fn set(&self, value: f64) {
        self.0.store(value, Ordering::Relaxed);
    }
}

struct HistogramImpl(metrics_util::AtomicBucket<f64>);
impl HistogramFn for HistogramImpl {
    fn record(&self, value: f64) {
        self.0.push(value);
    }
}

// ----------------- Helper types -----------------
// Rust doesn't have one of these for very sane reasons that we don't care about (unlike ints,
// most platforms don't have native atomic operations for floats, like add or sub), so we fake
// it a bit with bit casts.
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

// Quite cool to get GC hooks here, actually, even if we don't use them
impl Finalize for MetricsReport {}
