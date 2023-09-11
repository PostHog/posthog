use std::env;

use crate::time::SystemTime;

mod api;
mod capture;
mod event;
mod router;
mod sink;
mod time;
mod token;

#[tokio::main]
async fn main() {
    let use_print_sink = env::var("PRINT_SINK").is_ok();
    let address = env::var("ADDRESS").unwrap_or(String::from("127.0.0.1:3000"));

    let app = if use_print_sink {
        router::router(SystemTime {}, sink::PrintSink {})
    } else {
        let brokers = env::var("KAFKA_BROKERS").expect("Expected KAFKA_BROKERS");
        let topic = env::var("KAFKA_TOPIC").expect("Expected KAFKA_TOPIC");

        let sink = sink::KafkaSink::new(topic, brokers).unwrap();

        router::router(SystemTime {}, sink)
    };

    // initialize tracing
    tracing_subscriber::fmt::init();

    // run our app with hyper
    // `axum::Server` is a re-export of `hyper::Server`

    tracing::info!("listening on {}", address);

    axum::Server::bind(&address.parse().unwrap())
        .serve(app.into_make_service())
        .await
        .unwrap();
}
