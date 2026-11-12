//! The v4 Parquet sink: reads the index rows the v4 recorder writes to Kafka and rolls them into Parquet files under
//! `index/blocks/` and `index/images/` in the rrweb-v4 bucket. The format is in
//! `products/ai_training/docs/replay-data.md`, section "v4 dataset". It runs as a mode of the recorder's binary, so it
//! ships in the recorder's image.

pub mod batcher;
pub mod columns;
pub mod config;
pub mod consumer;
pub mod json;
mod metrics;
pub mod parquet;
pub mod row;
pub mod store;
pub mod watermark;

use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::{routing::get, Router};
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, Manager};
use metrics_exporter_prometheus::PrometheusBuilder;

use crate::batcher::{now_ms, Batcher, IndexStore, Options};
use crate::config::Config;
use crate::consumer::{consume, SinkConsumer};
use crate::store::S3Store;
use crate::watermark::CaptureWatermark;

/// A shutdown flush can write several files with a 120 second timeout each.
const SHUTDOWN_FLUSH: Duration = Duration::from_secs(300);

pub async fn run() -> Result<(), Box<dyn std::error::Error>> {
    let config = Config::init_from_env()?;
    config.validate()?;
    tracing::info!(topic = %config.topic, group = %config.group_id, "starting the v4 Parquet sink");

    // Before any component registers, because a component keeps the health gauge it creates at registration.
    let recorder = PrometheusBuilder::new().install_recorder()?;
    let mut manager = Manager::builder("replay-parquet-sink-v4")
        .with_global_shutdown_timeout(SHUTDOWN_FLUSH + Duration::from_secs(20))
        .build();
    let consumer_handle = manager.register(
        "consumer",
        ComponentOptions::new()
            .with_graceful_shutdown(SHUTDOWN_FLUSH + Duration::from_secs(10))
            .with_liveness_deadline(Duration::from_secs(60)),
    );
    let metrics_handle = manager.register(
        "metrics-server",
        ComponentOptions::new().is_observability(true),
    );
    let readiness = manager.readiness_handler();
    let liveness = manager.liveness_handler();
    let monitor = manager.monitor_background();

    let watermark = Arc::new(Mutex::new(CaptureWatermark::default()));
    let gauge = watermark.clone();
    let port = config.metrics_port;
    tokio::spawn(async move {
        let _guard = metrics_handle.process_scope();
        let router = Router::new()
            .route(
                "/_readiness",
                get(move || {
                    let readiness = readiness.clone();
                    async move { readiness.check().await }
                }),
            )
            .route("/_liveness", get(move || async move { liveness.check() }))
            .route(
                "/metrics",
                get(move || {
                    let mut text = recorder.render();
                    text.push_str(&gauge.lock().unwrap().render_gauge(now_ms()));
                    std::future::ready(text)
                }),
            );
        let listener = tokio::net::TcpListener::bind(format!("0.0.0.0:{port}"))
            .await
            .expect("bind metrics port");
        axum::serve(listener, router)
            .with_graceful_shutdown(metrics_handle.shutdown_signal())
            .await
            .expect("metrics server");
    });

    // The SDK's default HTTP client reads HTTPS_PROXY. A client built here reads no proxy settings, so S3 calls go
    // straight to the bucket, as the recorder's do.
    let http_client = aws_smithy_http_client::Builder::new()
        .tls_provider(aws_smithy_http_client::tls::Provider::Rustls(
            aws_smithy_http_client::tls::rustls_provider::CryptoMode::AwsLc,
        ))
        .build_https();
    let aws = aws_config::defaults(aws_config::BehaviorVersion::latest())
        .http_client(http_client)
        .load()
        .await;
    let s3 = aws_sdk_s3::Client::from_conf(
        aws_sdk_s3::config::Builder::from(&aws)
            .force_path_style(true)
            .build(),
    );
    let store: Arc<dyn IndexStore> = Arc::new(S3Store::new(s3, config.rrweb_bucket.clone()));
    let consumer = SinkConsumer::new(&config)?;
    let batcher = Batcher::new(
        store,
        consumer.offsets(),
        watermark,
        Options {
            flush_interval: Duration::from_millis(config.flush_interval_ms),
            max_rows: config.max_rows,
            max_bytes: config.max_bytes,
            row_group_rows: config.row_group_rows,
            owned_for: consumer::OWNED_FOR,
        },
        now_ms(),
    );
    tokio::spawn(consume(consumer, batcher, consumer_handle));

    monitor.wait().await?;
    Ok(())
}

#[cfg(test)]
pub(crate) mod testing {
    use ::parquet::file::reader::{FileReader, SerializedFileReader};
    use ::parquet::record::Field;
    use serde_json::{json, Map, Value};

    use crate::columns::{Column, Index, LeafType};

    pub fn block_row(session_id: &str) -> Value {
        let mut row = Map::new();
        for column in Index::Blocks.columns() {
            let value = match column {
                Column::Repeated { .. } | Column::List { .. } | Column::NullableList { .. } => {
                    json!([])
                }
                Column::Leaf(leaf) if leaf.optional => Value::Null,
                Column::Leaf(leaf) => match leaf.leaf {
                    LeafType::Utf8 => json!("x"),
                    LeafType::Boolean => json!(false),
                    LeafType::Int32 | LeafType::Int64 => json!(1),
                },
            };
            row.insert(column.name().to_owned(), value);
        }
        row.insert("session_id".to_owned(), json!(session_id));
        row.insert(
            "moments".to_owned(),
            json!([{"kind": "click", "window_id": "w1", "ts_ms": 1_000, "event_index": 3}]),
        );
        row.insert("url_fingerprints".to_owned(), json!(["b08517cee3ff5ecc"]));
        row.insert("window_ids".to_owned(), json!(["w1"]));
        Value::Object(row)
    }

    pub fn image_row(image_ref: &str) -> Value {
        json!({
            "team_id": 7,
            "key_month": "2026-10",
            "image_ref": image_ref,
            "pack_s3_key": "images/packs/dt=2026-10-15/7/1-0",
            "byte_start": 0,
            "byte_end": 99,
            "mime": "image/png",
            "byte_size": 60,
        })
    }

    pub fn read_rows(body: &[u8]) -> Vec<Vec<(String, Field)>> {
        let reader = SerializedFileReader::new(bytes::Bytes::copy_from_slice(body)).unwrap();
        reader
            .get_row_iter(None)
            .unwrap()
            .map(|row| {
                row.unwrap()
                    .get_column_iter()
                    .map(|(name, field)| (name.clone(), field.clone()))
                    .collect()
            })
            .collect()
    }

    pub fn read_column(body: &[u8], column: &str) -> Vec<Field> {
        read_rows(body)
            .into_iter()
            .map(|row| {
                row.into_iter()
                    .find(|(name, _)| name == column)
                    .map(|(_, field)| field)
                    .unwrap()
            })
            .collect()
    }
}
