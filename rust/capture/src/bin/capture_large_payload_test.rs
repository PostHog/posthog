use std::{io::Write, sync::Arc};

use flate2::{write::GzEncoder, Compression};
use serde_json::json;
use tokio::sync::Semaphore;

#[tokio::main]
async fn main() {
    let url = "http://localhost:3033/batch";

    let client = reqwest::Client::new();

    let large_prop = "a".repeat(1000 * 1000); // ~1MB
    let distint_id: &str = "nvjaeknfaeklnfk.am.s,";

    let body = json!(
        {
            "token": "testestest",
            "distinct_id": distint_id,
            "event": "test_large_payload",
            "properties": {
                "large_prop": large_prop
            }
        }
    )
    .to_string();

    println!("body size: {}", body.len());
    let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
    encoder.write_all(body.to_string().as_bytes()).unwrap();
    let compressed = encoder.finish().unwrap();
    println!("compressed size: {}", compressed.len());

    let concurrency = Arc::new(Semaphore::new(100));

    let mut count = 0;
    loop {
        let permit = concurrency.clone().acquire_owned().await.unwrap();
        let _client = client.clone();
        let _compressed = compressed.clone();
        tokio::spawn(async move {
            _client.post(url).body(_compressed).send().await.unwrap();
            drop(permit);
        });
        count += 1;
        if count % 200 == 0 {
            println!("sent: {}", count);
        }
    }
}
