use std::io::Write;
use std::time::Duration;

use anyhow::{Context, Result};
use axum::{
    body::Body,
    extract::Query,
    http::header::CONTENT_TYPE,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use flate2::write::GzEncoder;
use flate2::Compression;
use pprof::{flamegraph::Options, protos::Message, ProfilerGuardBuilder};
use serde::Deserialize;
use tokio::time::sleep;

#[derive(Deserialize)]
pub struct ProfileQueryParams {
    // seconds to run the profiler before taking snapshot
    pub seconds: Option<u64>,
    // profiler samplefrequency in Hz
    pub frequency: Option<i32>,

    // flamegraph SVG generator options
    pub image_width: Option<usize>,
}

//
// Generate a flamegraph SVG image of the profiler data
//
// Examples:
// curl -vsSL -X GET "http://<POD_URL>:<POD_PORT>/pprof/profile/report?seconds=10&frequency=200" > profile.pb.gz
//
// curl -vsSL -X GET "http://<POD_URL>:<POD_PORT>/pprof/profile/flamegraph?seconds=10&frequency=200&image_width=2500" > flamegraph.svg.gz
//
// curl -vsSL -X GET "http://<POD_URL>:<POD_PORT>/pprof/heap/report" > heap.pb.gz
//
// curl -vsSL -X GET "http://<POD_URL>:<POD_PORT>/pprof/heap/flamegraph" > heap.svg.gz
//
// NOTE: if deployed to k8s, use "kubectl port-forward" to forward the port
//       to your local machine, then replace <POD_URL> with "localhost"

const DEFAULT_IMAGE_WIDTH: usize = 2500;

pub async fn handle_profile_report(
    Query(params): Query<ProfileQueryParams>,
) -> Result<Response, Response> {
    let seconds = params.seconds.unwrap_or(10);
    let frequency = params.frequency.unwrap_or(200);

    match generate_report(frequency, seconds).await {
        Ok(body) => Ok((
            StatusCode::OK,
            [("Content-Type", "application/octet-stream")],
            body,
        )
            .into_response()),
        Err(e) => Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            [("Content-Type", "text/plain")],
            e.to_string(),
        )
            .into_response()),
    }
}

pub async fn handle_profile_flamegraph(
    Query(params): Query<ProfileQueryParams>,
) -> Result<Response, Response> {
    let seconds = params.seconds.unwrap_or(10);
    let frequency = params.frequency.unwrap_or(200);
    let image_width = params.image_width.unwrap_or(DEFAULT_IMAGE_WIDTH);

    match generate_flamegraph(frequency, seconds, image_width).await {
        Ok(body) => Ok((
            StatusCode::OK,
            [("Content-Type", "application/octet-stream")],
            body,
        )
            .into_response()),
        Err(e) => Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            [("Content-Type", "text/plain")],
            e.to_string(),
        )
            .into_response()),
    }
}

pub async fn handle_allocation_report() -> Result<impl IntoResponse, (StatusCode, String)> {
    let mut prof_ctl = jemalloc_pprof::PROF_CTL
        .as_ref()
        .ok_or_else(|| {
            (
                axum::http::StatusCode::FORBIDDEN,
                "jemalloc profiling not activated".into(),
            )
        })?
        .lock()
        .await;
    require_profiling_activated(&prof_ctl)?;

    let pprof = prof_ctl
        .dump_pprof()
        .map_err(|err| (StatusCode::INTERNAL_SERVER_ERROR, err.to_string()))?;
    Ok(pprof)
}

pub async fn handle_allocation_flamegraph() -> Result<impl IntoResponse, (StatusCode, String)> {
    let mut prof_ctl = jemalloc_pprof::PROF_CTL
        .as_ref()
        .ok_or_else(|| {
            (
                axum::http::StatusCode::FORBIDDEN,
                "jemalloc profiling not activated".into(),
            )
        })?
        .lock()
        .await;
    require_profiling_activated(&prof_ctl)?;

    let svg = prof_ctl
        .dump_flamegraph()
        .map_err(|err| (StatusCode::INTERNAL_SERVER_ERROR, err.to_string()))?;
    Response::builder()
        .header(CONTENT_TYPE, "image/svg+xml")
        .body(Body::from(svg))
        .map_err(|err| (StatusCode::INTERNAL_SERVER_ERROR, err.to_string()))
}

async fn generate_report(frequency: i32, seconds: u64) -> Result<Vec<u8>> {
    let guard = ProfilerGuardBuilder::default()
        .frequency(frequency)
        .blocklist(&["libc", "libgcc", "pthread", "vdso"])
        .build()
        .context("Failed to build profiler guard")?;

    sleep(Duration::from_secs(seconds)).await;

    let profile = guard
        .report()
        .build()
        .context("Failed to build profiler report")?
        .pprof()
        .context("Failed to build profiler profile")?;

    let mut body = Vec::new();
    let mut encoder = GzEncoder::new(&mut body, Compression::default());
    profile
        .write_to_writer(&mut encoder)
        .context("Failed to write profile to writer")?;
    encoder
        .finish()
        .context("Failed to finish encoding profile")?;

    Ok(body)
}

async fn generate_flamegraph(frequency: i32, seconds: u64, image_width: usize) -> Result<Vec<u8>> {
    let guard = ProfilerGuardBuilder::default()
        .frequency(frequency)
        .blocklist(&["libc", "libgcc", "pthread", "vdso"])
        .build()
        .context("Failed to build profiler guard")?;

    sleep(Duration::from_secs(seconds)).await;

    let mut options = Options::default();
    options.image_width = Some(image_width);
    let mut buf = Vec::new(); // buffer to store the flamegraph image

    // generate the flamegraph report with given options
    guard
        .report()
        .build()
        .context("Failed to build flamegraph report")?
        .flamegraph_with_options(&mut buf, &mut options)
        .context("Failed to populate flamegraph image buffer")?;

    // GZIP the flamegraph image buffer before returning it
    let mut body = Vec::new();
    let mut encoder = GzEncoder::new(&mut body, Compression::default());
    encoder
        .write_all(&buf)
        .context("Failed to write flamegraph image to buffer")?;
    encoder
        .finish()
        .context("Failed to finish encoding flamegraph image to buffer")?;

    Ok(body)
}

/// Checks whether jemalloc profiling is activated and returns an error response if not
fn require_profiling_activated(
    prof_ctl: &jemalloc_pprof::JemallocProfCtl,
) -> Result<(), (StatusCode, String)> {
    if prof_ctl.activated() {
        Ok(())
    } else {
        Err((
            axum::http::StatusCode::FORBIDDEN,
            "heap profiling not activated".into(),
        ))
    }
}
