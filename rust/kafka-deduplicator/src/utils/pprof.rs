use anyhow::{Context, Result};
use axum::{
    extract::Query,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use flate2::write::GzEncoder;
use flate2::Compression;
use pprof::{protos::Message, ProfilerGuardBuilder};
use serde::Deserialize;
use std::time::Duration;
use tokio::time::sleep;

#[derive(Deserialize)]
pub struct ProfileQueryParams {
    // seconds to run the profiler before taking snapshot
    pub seconds: Option<u64>,
    // profiler samplefrequency in Hz
    pub frequency: Option<i32>,
}

pub async fn handle_profile(
    Query(params): Query<ProfileQueryParams>,
) -> Result<Response, Response> {
    let seconds = params.seconds.unwrap_or(10);
    let frequency = params.frequency.unwrap_or(200);

    match generate_report(frequency, seconds).await {
        Ok(body) => Ok((
            StatusCode::OK,
            [("Content-Type", "application/octet-stream")],
            [(
                "Content-Disposition",
                "attachment; filename=\"profile.pb.gz\"",
            )],
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
