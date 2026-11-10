//! Workloads and sizes match `framework-bench.ts`. A current-thread runtime matches the single Node event loop.

use std::sync::Arc;

use criterion::{criterion_group, BenchmarkId, Criterion, Throughput};
use ingestion_framework::{
    before_batch_step, chunk_step, create_ok_context, new_batching_pipeline, new_chunk_pipeline,
    new_pipeline, ok, passthrough_after_batch_step, per_element, step, BatchingPipelineOptions,
    ChunkProcessingStep, DynChunkPipeline, OkResultWithContext, Outcome, ProcessingStep, WithBatch,
};

const SIZES: [usize; 3] = [1, 100, 10_000];

fn inc(name: &str) -> ProcessingStep<i64, i64> {
    ProcessingStep::sync(name, |v: i64| Ok(ok(v + 1)))
}

fn inc_chunk(name: &str) -> ChunkProcessingStep<i64, i64> {
    ChunkProcessingStep::sync(name, |v: Vec<i64>| {
        Ok(v.into_iter().map(|x| ok(x + 1)).collect())
    })
}

fn inputs(n: usize) -> Vec<OkResultWithContext<i64, ()>> {
    (0..n as i64).map(|v| create_ok_context(v, ())).collect()
}

fn current_thread() -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap()
}

fn multi_thread() -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(4)
        .enable_all()
        .build()
        .unwrap()
}

async fn drain(pipeline: &DynChunkPipeline<i64, i64, (), ()>) -> usize {
    let mut n = 0;
    while let Some(chunk) = pipeline.next().await.unwrap() {
        n += chunk.len();
    }
    n
}

fn step_pipeline_5_steps(c: &mut Criterion) {
    let rt = current_thread();
    let pipeline = new_pipeline::<i64, ()>()
        .pipe(inc("s1"))
        .pipe(inc("s2"))
        .pipe(inc("s3"))
        .pipe(inc("s4"))
        .pipe(inc("s5"))
        .build();
    let mut group = c.benchmark_group("step_pipeline_5_steps");
    for n in SIZES {
        group.throughput(Throughput::Elements(n as u64));
        group.bench_with_input(BenchmarkId::from_parameter(n), &n, |b, &n| {
            b.to_async(&rt).iter(|| {
                let pipeline = pipeline.clone();
                async move {
                    for input in inputs(n) {
                        pipeline.process(input).await.unwrap();
                    }
                }
            })
        });
    }
    group.finish();
}

fn pipe_chunk_chain(c: &mut Criterion) {
    let rt = current_thread();
    let mut group = c.benchmark_group("pipe_chunk_5_steps");
    for n in SIZES {
        group.throughput(Throughput::Elements(n as u64));
        group.bench_with_input(BenchmarkId::from_parameter(n), &n, |b, &n| {
            b.to_async(&rt).iter(|| async move {
                let pipeline = new_chunk_pipeline::<i64, ()>()
                    .pipe_chunk(inc_chunk("c1"))
                    .pipe_chunk(inc_chunk("c2"))
                    .pipe_chunk(inc_chunk("c3"))
                    .pipe_chunk(inc_chunk("c4"))
                    .pipe_chunk(inc_chunk("c5"))
                    .build();
                pipeline.feed(inputs(n));
                assert_eq!(drain(&pipeline).await, n);
            })
        });
    }
    group.finish();
}

fn concurrently(c: &mut Criterion) {
    for (label, rt) in [
        ("concurrently_max50", current_thread()),
        ("concurrently_max50_multi_thread", multi_thread()),
    ] {
        let mut group = c.benchmark_group(label);
        for n in SIZES {
            group.throughput(Throughput::Elements(n as u64));
            group.bench_with_input(BenchmarkId::from_parameter(n), &n, |b, &n| {
                b.to_async(&rt).iter(|| async move {
                    let pipeline = new_chunk_pipeline::<i64, ()>()
                        .concurrently(|b| b.pipe(inc("s1")).pipe(inc("s2")), Some(50))
                        .build();
                    pipeline.feed(inputs(n));
                    assert_eq!(drain(&pipeline).await, n);
                })
            });
        }
        group.finish();
    }
}

fn per_element_max50(c: &mut Criterion) {
    let rt = current_thread();
    let mut group = c.benchmark_group("per_element_max50");
    for n in SIZES {
        group.throughput(Throughput::Elements(n as u64));
        group.bench_with_input(BenchmarkId::from_parameter(n), &n, |b, &n| {
            b.to_async(&rt).iter(|| async move {
                let pipeline = new_chunk_pipeline::<i64, ()>()
                    .pipe_chunk(per_element(inc("s1"), Some(50)))
                    .pipe_chunk(per_element(inc("s2"), Some(50)))
                    .build();
                pipeline.feed(inputs(n));
                assert_eq!(drain(&pipeline).await, n);
            })
        });
    }
    group.finish();
}

fn concurrently_per_group(c: &mut Criterion) {
    for (label, rt) in [
        ("concurrently_per_group_16", current_thread()),
        ("concurrently_per_group_16_multi_thread", multi_thread()),
    ] {
        let mut group = c.benchmark_group(label);
        for n in SIZES {
            group.throughput(Throughput::Elements(n as u64));
            group.bench_with_input(BenchmarkId::from_parameter(n), &n, |b, &n| {
                b.to_async(&rt).iter(|| async move {
                    let pipeline = new_chunk_pipeline::<i64, ()>()
                        .concurrently_per_group(
                            |v: &i64| v % 16,
                            |g| g.sequentially(|b| b.pipe(inc("s1")).pipe(inc("s2"))),
                            None,
                        )
                        .build();
                    pipeline.feed(inputs(n));
                    assert_eq!(drain(&pipeline).await, n);
                })
            });
        }
        group.finish();
    }
}

type V = WithBatch<i64, u64>;

fn batching(c: &mut Criterion) {
    for (label, rt) in [
        ("batching_full", current_thread()),
        ("batching_full_multi_thread", multi_thread()),
    ] {
        let mut group = c.benchmark_group(label);
        for n in SIZES {
            group.throughput(Throughput::Elements(n as u64));
            group.bench_with_input(BenchmarkId::from_parameter(n), &n, |b, &n| {
                b.to_async(&rt).iter(|| async move {
                    let pipeline = Arc::new(new_batching_pipeline::<i64, V, (), (), u64, ()>(
                        |b| b.pipe(before_batch_step("before", |id| id)),
                        |b| {
                            b.pipe_chunk(chunk_step("prepare", |v: Vec<V>| async move {
                                Ok(v.into_iter()
                                    .map(|mut x| {
                                        x.value += 1;
                                        ok(x)
                                    })
                                    .collect())
                            }))
                            .concurrently_per_group(
                                |v: &V| v.value % 16,
                                |g| {
                                    g.sequentially(|s| {
                                        s.pipe(step("work", |mut v: V| async move {
                                            v.value += 1;
                                            Ok(ok(v))
                                        }))
                                    })
                                },
                                Some(50),
                            )
                            .gather()
                        },
                        |b| b.pipe(passthrough_after_batch_step("after")),
                        BatchingPipelineOptions::default(),
                    ));
                    assert!(pipeline.feed(inputs(n), (), None).await.unwrap().is_ok());
                    let done = pipeline.next().await.unwrap().unwrap();
                    assert_eq!(done.elements.len(), n);
                    // Each input `i` passes two `+ 1` steps, as in the Node workload.
                    let sum: i64 = done
                        .elements
                        .iter()
                        .map(|e| match &e.result {
                            Outcome::Ok(v) => v.value,
                            Outcome::NonOk(_) => panic!("batching_full produced a non-ok result"),
                        })
                        .sum();
                    let n = n as i64;
                    assert_eq!(sum, n * (n - 1) / 2 + 2 * n);
                })
            });
        }
        group.finish();
    }
}

criterion_group!(
    benches,
    step_pipeline_5_steps,
    pipe_chunk_chain,
    concurrently,
    per_element_max50,
    concurrently_per_group,
    batching
);
/// Without a recorder every metric call is a no-op, while Node updates real `prom-client` metrics.
fn install_metrics_recorder() {
    const BUCKETS: &[f64] = &[
        1.0, 5.0, 10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0, 10000.0,
    ];
    let handle = metrics_exporter_prometheus::PrometheusBuilder::new()
        .set_buckets(BUCKETS)
        .expect("buckets are not empty")
        .install_recorder()
        .expect("no other recorder is installed");
    // Histogram samples stay buffered until upkeep drains them, as the production exporter does.
    std::thread::spawn(move || loop {
        std::thread::sleep(std::time::Duration::from_secs(1));
        handle.run_upkeep();
    });
}

fn main() {
    install_metrics_recorder();
    benches();
    Criterion::default().configure_from_args().final_summary();
}
