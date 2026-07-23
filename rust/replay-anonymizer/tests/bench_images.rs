//! Manual benchmark for inline vs deferred-parallel image scrubbing. Ignored in CI (timing is
//! machine-dependent); run with:
//!
//! ```sh
//! cargo test --release -p posthog-replay-anonymizer --test bench_images -- --ignored --nocapture
//! ```

use std::time::Instant;

use base64::Engine;
use posthog_replay_anonymizer::snapshot::{anonymize_kafka_payload_opts, AnonymizeOpts};
use posthog_replay_anonymizer::{AllowLists, ImagePolicy};
use serde_json::json;

fn image_data_uri(side: u32, seed: u8, format: image::ImageFormat) -> String {
    let mut img = image::RgbaImage::new(side, side);
    for (x, y, px) in img.enumerate_pixels_mut() {
        *px = image::Rgba([
            (x as u8).wrapping_mul(seed),
            (y as u8).wrapping_add(seed),
            seed,
            255,
        ]);
    }
    let img = if format == image::ImageFormat::Jpeg {
        // JPEG has no alpha channel.
        image::DynamicImage::ImageRgb8(image::DynamicImage::ImageRgba8(img).to_rgb8())
    } else {
        image::DynamicImage::ImageRgba8(img)
    };
    let mut buf = Vec::new();
    img.write_to(&mut std::io::Cursor::new(&mut buf), format)
        .unwrap();
    let mime = if format == image::ImageFormat::Jpeg {
        "jpeg"
    } else {
        "png"
    };
    format!(
        "data:image/{mime};base64,{}",
        base64::engine::general_purpose::STANDARD.encode(buf)
    )
}

fn payload(images: usize, side: u32, duplicates: usize, format: image::ImageFormat) -> Vec<u8> {
    let mut children = Vec::new();
    for i in 0..images {
        let uri = image_data_uri(side, (i + 1) as u8, format);
        for d in 0..=duplicates {
            children.push(json!({
                "type": 2,
                "id": 10 + children.len(),
                "tagName": "img",
                "attributes": { "src": uri, "alt": format!("img-{i}-{d}") },
                "childNodes": [],
            }));
        }
    }
    let inner = json!({
        "event": "$snapshot_items",
        "properties": {
            "$session_id": "bench-session",
            "$window_id": "w",
            "$snapshot_items": [{
                "type": 2,
                "timestamp": 1_700_000_000_000u64,
                "data": {
                    "node": { "type": 0, "id": 1, "childNodes": children },
                    "initialOffset": { "top": 0, "left": 0 },
                },
            }],
        },
    });
    serde_json::to_string(&json!({
        "distinct_id": "d",
        "data": inner.to_string(),
    }))
    .unwrap()
    .into_bytes()
}

fn run(allow: &AllowLists, payload: &[u8], policy: ImagePolicy, iters: usize) -> Vec<u128> {
    let mut samples = Vec::with_capacity(iters);
    for _ in 0..iters {
        let mut bytes = payload.to_vec();
        let start = Instant::now();
        let out = anonymize_kafka_payload_opts(
            allow,
            &mut bytes,
            AnonymizeOpts {
                image_policy: policy,
                ..Default::default()
            },
        )
        .expect("bench payload must anonymize");
        samples.push(start.elapsed().as_micros());
        assert!(!out.lines.is_empty());
    }
    samples.sort_unstable();
    samples
}

#[test]
#[ignore = "manual benchmark; run in release with --nocapture"]
fn bench_inline_vs_parallel_images() {
    let allow = AllowLists::new(Vec::<String>::new(), Vec::<String>::new());
    println!(
        "image workers: REPLAY_ANONYMIZER_IMAGE_THREADS={}",
        std::env::var("REPLAY_ANONYMIZER_IMAGE_THREADS").unwrap_or_else(|_| "(default)".into())
    );
    for (images, side, duplicates, format) in [
        (4usize, 256u32, 0usize, image::ImageFormat::Png),
        (16, 256, 0, image::ImageFormat::Png),
        (16, 512, 0, image::ImageFormat::Png),
        (16, 256, 3, image::ImageFormat::Png),
        (4, 512, 0, image::ImageFormat::Jpeg),
        (16, 1024, 0, image::ImageFormat::Jpeg),
        (4, 2048, 0, image::ImageFormat::Jpeg),
    ] {
        let payload = payload(images, side, duplicates, format);
        // Warm both paths (decoder init, worker pool spawn) before sampling.
        run(&allow, &payload, ImagePolicy::Inline, 1);
        run(&allow, &payload, ImagePolicy::Parallel, 1);
        let inline = run(&allow, &payload, ImagePolicy::Inline, 7);
        let parallel = run(&allow, &payload, ImagePolicy::Parallel, 7);
        let median = |s: &Vec<u128>| s[s.len() / 2];
        println!(
            "{images:2} distinct {side}x{side} {format:?} x{} occurrences ({:6} KB payload): inline {:7}us  parallel {:7}us  ({:.2}x)",
            duplicates + 1,
            payload.len() / 1024,
            median(&inline),
            median(&parallel),
            median(&inline) as f64 / median(&parallel) as f64,
        );
    }
}
