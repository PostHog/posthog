mod common;

use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use common::{
    h2_frame, read_h2_frame, H2Frame, TestLeaderService, H2_FRAME_SETTINGS, H2_FRAME_WINDOW_UPDATE,
    H2_PREFACE,
};
use personhog_coordination::changelog::LiveChangelog;
use personhog_coordination::types::ChangelogConfig;
use personhog_proto::personhog::leader::v1::person_hog_leader_server::PersonHogLeaderServer;
use personhog_router::backend::discovery::{build_discovered_endpoint, EndpointConfig};
use personhog_router::backend::{
    ChannelBackend, DnsBackendConfig, LeaderBackend, LeaderBackendConfig, StashTable,
};
use personhog_router::config::{Http2Windows, RetryConfig, WindowSize};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::RwLock;
use tonic::transport::{Channel, Server};
use tower::{Service, ServiceExt};

const DEFAULT_WINDOW: u32 = 65_535;
const HYPER_SERVER_STREAM_WINDOW: u32 = 1 << 20;
const HYPER_SERVER_CONNECTION_WINDOW: u32 = 1 << 20;
const HYPER_CLIENT_STREAM_WINDOW: u32 = 2 << 20;
const HYPER_CLIENT_CONNECTION_WINDOW: u32 = 5 << 20;
const STREAM_WINDOW: u32 = 4 << 20;
const CONNECTION_WINDOW: u32 = 8 << 20;
const SETTINGS_INITIAL_WINDOW_SIZE: u16 = 0x4;

#[derive(Debug, Default, PartialEq, Eq)]
struct AdvertisedWindows {
    stream: Option<u32>,
    connection_increment: Option<u32>,
}

async fn read_advertised_windows(stream: &mut TcpStream) -> AdvertisedWindows {
    let mut seen = AdvertisedWindows::default();
    let read_all = async {
        while seen.stream.is_none() || seen.connection_increment.is_none() {
            let H2Frame {
                frame_type,
                stream_id,
                payload,
                ..
            } = read_h2_frame(stream).await;
            match frame_type {
                H2_FRAME_SETTINGS => {
                    for entry in payload.chunks_exact(6) {
                        let id = u16::from_be_bytes([entry[0], entry[1]]);
                        let value = u32::from_be_bytes([entry[2], entry[3], entry[4], entry[5]]);
                        if id == SETTINGS_INITIAL_WINDOW_SIZE {
                            seen.stream = Some(value);
                        }
                    }
                }
                H2_FRAME_WINDOW_UPDATE if stream_id == 0 => {
                    let increment =
                        u32::from_be_bytes([payload[0], payload[1], payload[2], payload[3]])
                            & 0x7fff_ffff;
                    seen.connection_increment = Some(increment);
                }
                _ => {}
            }
        }
    };
    tokio::time::timeout(Duration::from_secs(5), read_all)
        .await
        .expect("peer advertised both windows");
    seen
}

fn windows(configured: bool) -> Http2Windows {
    if configured {
        Http2Windows::new(
            WindowSize::bytes(STREAM_WINDOW).unwrap(),
            WindowSize::bytes(CONNECTION_WINDOW).unwrap(),
        )
    } else {
        Http2Windows::default()
    }
}

fn expected(configured: bool, library_stream: u32, library_connection: u32) -> AdvertisedWindows {
    let (stream, connection) = if configured {
        (STREAM_WINDOW, CONNECTION_WINDOW)
    } else {
        (library_stream, library_connection)
    };
    AdvertisedWindows {
        stream: Some(stream),
        connection_increment: Some(connection - DEFAULT_WINDOW),
    }
}

fn retry_config() -> RetryConfig {
    RetryConfig {
        max_retries: 0,
        initial_backoff_ms: 1,
        max_backoff_ms: 1,
    }
}

fn dns_channel(addr: SocketAddr, http2_windows: Http2Windows) -> Channel {
    ChannelBackend::new_dns(
        "replica",
        DnsBackendConfig {
            url: format!("http://{addr}"),
            timeout: Duration::from_secs(5),
            retry_config: retry_config(),
            keepalive_interval: None,
            keepalive_timeout: None,
            http2_windows,
            num_channels: 1,
        },
    )
    .channel()
}

fn discovered_channel(addr: SocketAddr, http2_windows: Http2Windows) -> Channel {
    build_discovered_endpoint(
        addr,
        &EndpointConfig {
            timeout: Duration::from_secs(5),
            connect_timeout: Duration::from_secs(5),
            keepalive_interval: None,
            keepalive_timeout: None,
            http2_windows,
        },
    )
    .connect_lazy()
}

async fn leader_channel(addr: SocketAddr, http2_windows: Http2Windows) -> Channel {
    let mut routing = HashMap::new();
    routing.insert(0, "leader-0".to_string());
    let changelog = LiveChangelog::new(ChangelogConfig::new("personhog_updates", 1));
    let backend = LeaderBackend::new(
        Arc::new(RwLock::new(routing)),
        Arc::new(move |_| Some(format!("http://{addr}"))),
        LeaderBackendConfig {
            changelog: changelog.clone(),
            timeout: Duration::from_secs(5),
            num_channels: 1,
            http2_windows,
        },
        StashTable::with_bounds(usize::MAX, usize::MAX, changelog),
    );
    backend.resolve_leader_channel(0).await.unwrap()
}

fn drive(mut channel: Channel) {
    tokio::spawn(async move {
        let request = http::Request::builder()
            .method(http::Method::POST)
            .uri("http://unused/svc/Method")
            .version(http::Version::HTTP_2)
            .body(tonic::body::empty_body())
            .unwrap();
        if let Ok(ready) = channel.ready().await {
            drop(ready.call(request).await);
        }
    });
}

#[tokio::test]
async fn every_outbound_channel_builder_advertises_the_configured_windows() {
    for configured in [true, false] {
        for builder in ["dns", "discovery", "leader"] {
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let addr = listener.local_addr().unwrap();
            let http2_windows = windows(configured);
            let channel = match builder {
                "dns" => dns_channel(addr, http2_windows),
                "discovery" => discovered_channel(addr, http2_windows),
                _ => leader_channel(addr, http2_windows).await,
            };
            drive(channel);

            let (mut peer, _) = listener.accept().await.unwrap();
            let mut preface = [0u8; H2_PREFACE.len()];
            peer.read_exact(&mut preface).await.unwrap();
            assert_eq!(&preface, H2_PREFACE, "{builder}");
            peer.write_all(&h2_frame(H2_FRAME_SETTINGS, 0, 0, &[]))
                .await
                .unwrap();

            let seen = read_advertised_windows(&mut peer).await;
            assert_eq!(
                seen,
                expected(
                    configured,
                    HYPER_CLIENT_STREAM_WINDOW,
                    HYPER_CLIENT_CONNECTION_WINDOW
                ),
                "{builder} configured={configured}"
            );
        }
    }
}

#[tokio::test]
async fn the_server_advertises_the_configured_windows() {
    for configured in [true, false] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let mut server = windows(configured).apply_to_server(Server::builder());
        tokio::spawn(async move {
            server
                .add_service(PersonHogLeaderServer::new(TestLeaderService::new()))
                .serve_with_incoming(tokio_stream::wrappers::TcpListenerStream::new(listener))
                .await
                .unwrap();
        });

        let mut peer = TcpStream::connect(addr).await.unwrap();
        peer.write_all(H2_PREFACE).await.unwrap();
        peer.write_all(&h2_frame(H2_FRAME_SETTINGS, 0, 0, &[]))
            .await
            .unwrap();

        let seen = read_advertised_windows(&mut peer).await;
        assert_eq!(
            seen,
            expected(
                configured,
                HYPER_SERVER_STREAM_WINDOW,
                HYPER_SERVER_CONNECTION_WINDOW
            ),
            "configured={configured}"
        );
    }
}
