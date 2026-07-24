//! Proofs for the async combinators: FIFO ordering, bounded + real concurrency,
//! strict within-group ordering, and positional verdict reassembly.
//!
//! All concurrency is proved **deterministically** — a shared in-flight counter plus
//! explicit `yield_now` suspension points, never `sleep`. Tests run on tokio's
//! current-thread runtime, so polling order is deterministic.

use capture_pipelines_poc::{
    builder, concurrently, concurrently_per_group, yield_now, AsyncProcessor, NoOutputs, Step,
    StepResult,
};
use std::sync::atomic::{AtomicUsize, Ordering::SeqCst};
use std::sync::Mutex;

/// A processor that records how many of its calls overlap (max in-flight) and the
/// order it sees items per key, then returns `value * 10`. Two `yield_now`s make the
/// overlap window deterministic without sleeping.
struct Probe {
    in_flight: AtomicUsize,
    max_in_flight: AtomicUsize,
    order: Mutex<Vec<(char, i64)>>,
}

impl Probe {
    fn new() -> Self {
        Probe {
            in_flight: AtomicUsize::new(0),
            max_in_flight: AtomicUsize::new(0),
            order: Mutex::new(Vec::new()),
        }
    }
    fn max_seen(&self) -> usize {
        self.max_in_flight.load(SeqCst)
    }
    fn order_for(&self, key: char) -> Vec<i64> {
        self.order
            .lock()
            .unwrap()
            .iter()
            .filter(|(k, _)| *k == key)
            .map(|(_, v)| *v)
            .collect()
    }
}

impl AsyncProcessor for Probe {
    type In = (char, i64);
    type Out = i64;
    type Outputs = NoOutputs;

    async fn process(&self, item: (char, i64)) -> StepResult<i64, NoOutputs> {
        let (key, value) = item;
        let now = self.in_flight.fetch_add(1, SeqCst) + 1;
        self.max_in_flight.fetch_max(now, SeqCst);
        self.order.lock().unwrap().push((key, value));
        yield_now().await;
        yield_now().await;
        self.in_flight.fetch_sub(1, SeqCst);
        StepResult::Continue(value * 10)
    }

    fn name(&self) -> &'static str {
        "probe"
    }
}

fn values(results: Vec<StepResult<i64, NoOutputs>>) -> Vec<i64> {
    results
        .into_iter()
        .map(|r| match r {
            StepResult::Continue(v) => v,
            _ => panic!("expected continue"),
        })
        .collect()
}

#[tokio::test]
async fn concurrently_preserves_fifo_order_and_runs_bounded_concurrently() {
    let probe = Probe::new();
    let items = vec![('x', 1), ('x', 2), ('x', 3), ('x', 4)];

    let out = concurrently(2, &probe, items).await;

    // Emission is in input (FIFO) order regardless of completion order.
    assert_eq!(values(out), vec![10, 20, 30, 40]);
    // `buffered(2)` keeps exactly 2 items in flight at the peak — real, bounded concurrency.
    assert_eq!(probe.max_seen(), 2);
}

#[tokio::test]
async fn concurrently_per_group_orders_within_group_and_runs_groups_concurrently() {
    let probe = Probe::new();
    // Interleaved keys; indices: A@0,2,5  B@1,4  C@3.
    let items = vec![('A', 1), ('B', 2), ('A', 3), ('C', 4), ('B', 5), ('A', 6)];

    // Unbounded groups (3): all three groups run concurrently.
    let out = concurrently_per_group(3, |&(k, _)| k, &probe, items).await;

    // (c) Positional verdicts: output i corresponds to input i.
    assert_eq!(values(out), vec![10, 20, 30, 40, 50, 60]);
    // (a) Within-group order is strictly the input order for that key.
    assert_eq!(probe.order_for('A'), vec![1, 3, 6]);
    assert_eq!(probe.order_for('B'), vec![2, 5]);
    assert_eq!(probe.order_for('C'), vec![4]);
    // (b) Cross-group concurrency actually happened: all 3 groups overlapped.
    assert_eq!(probe.max_seen(), 3);
}

#[tokio::test]
async fn concurrently_per_group_bounds_group_concurrency() {
    let probe = Probe::new();
    let items = vec![('A', 1), ('B', 2), ('C', 3), ('A', 4)];

    // max_groups = 1: groups run one at a time, so at most one item is ever in flight.
    let out = concurrently_per_group(1, |&(k, _)| k, &probe, items).await;

    assert_eq!(values(out), vec![10, 20, 30, 40]); // still positional
    assert_eq!(probe.order_for('A'), vec![1, 4]); // still in-order within a group
    assert_eq!(probe.max_seen(), 1); // bounded to one group at a time
}

#[test]
fn batching_hooks_are_plain_functions_around_the_runner() {
    // Node's BatchingPipeline before/after-batch hooks need no framework machinery
    // here — they are ordinary calls that bracket a `run_chunk`.
    struct Count;
    impl<Fx> Step<i64, Fx> for Count {
        type Out = i64;
        type Outputs = NoOutputs;
        fn apply(&self, event: i64, _fx: &mut Fx) -> StepResult<i64, NoOutputs> {
            StepResult::Continue(event)
        }
        fn name(&self) -> &'static str {
            "count"
        }
    }

    fn before_batch(processed: &mut usize) {
        *processed = 0;
    }
    fn after_batch(processed: usize) -> usize {
        processed
    }

    let pipeline = builder::<i64>().step(Count).build();
    let mut fx = ();
    let mut processed = 99;

    before_batch(&mut processed);
    let out = pipeline.run_chunk(vec![1, 2, 3], &mut fx);
    processed = out.len();

    assert_eq!(after_batch(processed), 3);
}
