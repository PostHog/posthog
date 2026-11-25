use anyhow::Result;
use axum::{
    Json, Router,
    body::{Body, Bytes},
    extract::{Path, Query, Request, State},
    http::{HeaderValue, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response, Sse, sse::Event},
    routing::{get, post, put},
};
use chrono::Utc;
use meep_client::{Client, HttpTransport};
use meep_connections::{Connection, Health};
use meep_engine::Engine;
use meep_topic::{Envelope, TopicId};
use meep_wire::*;
use parking_lot::Mutex;
use serde::Deserialize;
use std::{
    collections::BTreeSet,
    convert::Infallible,
    io,
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicUsize, Ordering::SeqCst},
    },
    time::Duration,
};
use tokio::{
    net::TcpListener,
    sync::{broadcast, oneshot, watch},
    task::JoinHandle,
};

const TOKEN: &str = "loopback-device";

pub struct Server {
    pub app: Arc<App>,
    url: String,
    task: JoinHandle<()>,
}

type Gate = (oneshot::Sender<()>, oneshot::Receiver<()>);

pub struct App {
    pub engine: Engine,
    pub offline: AtomicBool,
    pub unauthorized: AtomicBool,
    pub retry_next: AtomicBool,
    pub lose_receipt: AtomicBool,
    pub fail_snapshot: AtomicBool,
    pub reject_upload: AtomicBool,
    pub requests: AtomicUsize,
    pub batches: Mutex<Vec<Vec<Envelope>>>,
    pub cursors: Mutex<Vec<u64>>,
    pub stream_cursor: watch::Sender<Option<u64>>,
    gate: Mutex<Option<Gate>>,
}

impl Server {
    pub async fn start() -> Result<Self> {
        let app = Arc::new(App {
            engine: Engine::in_memory().await?,
            offline: false.into(),
            unauthorized: false.into(),
            retry_next: false.into(),
            lose_receipt: false.into(),
            fail_snapshot: false.into(),
            reject_upload: false.into(),
            requests: 0.into(),
            batches: Mutex::default(),
            cursors: Mutex::default(),
            gate: Mutex::default(),
            stream_cursor: watch::channel(None).0,
        });
        let router = Router::new()
            .route("/v1/health", get(|| async { Json(serde_json::json!({"owner_id": uuid::Uuid::nil(), "version": "test", "cursor": 0, "posthog": false})) }))
            .route("/v1/commands", post(commands))
            .route("/v1/changes", get(changes))
            .route(
                "/v1/deletions/ack",
                post(
                    |State(app): State<Arc<App>>, Json(ack): Json<DeletionAck>| async move {
                        for (topic, revision) in ack.topics {
                            app.engine
                                .acknowledge_deletion(topic, revision, ack.replica)
                                .await
                                .unwrap();
                        }
                        Json(())
                    },
                ),
            )
            .route("/v1/topics/{topic}", get(snapshot))
            .route("/v1/stream", get(stream))
            .route(
                "/v1/views",
                get(|| async { Json(Vec::<meep_wire::views::View>::new()) }),
            )
            .route("/v1/connections", get(connections))
            .route("/v1/connections/{id}", put(put_connection))
            .route(
                "/v1/topics/{topic}/files/{*path}",
                get(get_file).put(put_file),
            )
            .layer(middleware::from_fn_with_state(app.clone(), authorize))
            .with_state(app.clone());
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let url = format!("http://{}", listener.local_addr()?);
        let task = tokio::spawn(async move {
            axum::serve(listener, router).await.expect("serve loopback");
        });
        Ok(Self { app, url, task })
    }

    pub fn client(&self, path: &std::path::Path) -> Result<Client> {
        Client::open(path, Arc::new(HttpTransport::new(&self.url, TOKEN)?))
    }

    pub fn pause_next_pull(&self) -> (oneshot::Receiver<()>, oneshot::Sender<()>) {
        let (started, started_rx) = oneshot::channel();
        let (resume, resume_rx) = oneshot::channel();
        *self.app.gate.lock() = Some((started, resume_rx));
        (started_rx, resume)
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        self.task.abort();
    }
}

fn error(status: StatusCode, code: &str, message: impl ToString) -> Response {
    (
        status,
        Json(ApiError {
            code: code.into(),
            message: message.to_string(),
        }),
    )
        .into_response()
}

async fn authorize(State(app): State<Arc<App>>, req: Request, next: Next) -> Response {
    app.requests.fetch_add(1, SeqCst);
    if app.unauthorized.load(SeqCst)
        || req
            .headers()
            .get("authorization")
            .and_then(|v| v.to_str().ok())
            != Some("Bearer loopback-device")
    {
        return error(StatusCode::UNAUTHORIZED, "unauthorized", "device refused");
    }
    if app.offline.load(SeqCst) {
        return error(
            StatusCode::SERVICE_UNAVAILABLE,
            "offline",
            "server unavailable",
        );
    }
    next.run(req).await
}

async fn commands(State(app): State<Arc<App>>, Json(batch): Json<CommandBatch>) -> Response {
    app.batches.lock().push(batch.commands.clone());
    let mut results = vec![];
    for envelope in batch.commands {
        let (id, topic) = (envelope.id, envelope.topic);
        if app.retry_next.swap(false, SeqCst) {
            results.push(CommandResult::Retry {
                id,
                reason: "Fixture unavailable".into(),
            });
            continue;
        }
        results.push(match app.engine.apply(envelope).await {
            Ok(applied) => CommandResult::Applied {
                id,
                topic,
                revision: applied.revision,
            },
            Err(err) => CommandResult::Rejected {
                id,
                reason: err.to_string(),
            },
        });
    }
    if app.lose_receipt.swap(false, SeqCst) {
        // The engine committed the commands, then the HTTP connection lost the body.
        let body =
            futures_util::stream::iter([Err::<Bytes, _>(io::Error::other("response interrupted"))]);
        return Response::new(Body::from_stream(body));
    }
    Json(CommandResults { results }).into_response()
}

fn latest(engine: &Engine, topic: TopicId) -> TopicSnapshot {
    engine.snapshot(topic).expect("known topic")
}

async fn snapshot(State(app): State<Arc<App>>, Path(topic): Path<TopicId>) -> Response {
    if app.fail_snapshot.swap(false, SeqCst) {
        return error(
            StatusCode::SERVICE_UNAVAILABLE,
            "offline",
            "snapshot unavailable",
        );
    }
    Json(latest(&app.engine, topic)).into_response()
}

#[derive(Deserialize)]
struct Cursor {
    replica: Option<uuid::Uuid>,
    cursor: u64,
}

async fn changes(
    State(app): State<Arc<App>>,
    Query(Cursor { cursor, replica }): Query<Cursor>,
) -> Json<ChangePage> {
    app.cursors.lock().push(cursor);
    let gate = app.gate.lock().take();
    if let Some((started, resume)) = gate {
        let _ = started.send(());
        let _ = resume.await;
    }
    // Small pages make every test exercise the exclusive cursor when multiple revisions exist.
    let (revisions, _) = app.engine.changes_since(cursor).expect("change log");
    let count = revisions.len().min(2);
    let ids = revisions[..count]
        .iter()
        .map(|r| r.topic)
        .collect::<BTreeSet<_>>();
    let mut topics = vec![];
    for t in ids {
        topics.push(if let Some(r) = replica {
            app.engine.replica_snapshot(t, r).await.unwrap()
        } else {
            latest(&app.engine, t)
        });
    }
    Json(ChangePage {
        topics,
        cursor: cursor + count as u64,
        more: revisions.len() > count,
    })
}

async fn stream(
    State(app): State<Arc<App>>,
    Query(Cursor { mut cursor, .. }): Query<Cursor>,
) -> Response {
    let mut events = app.engine.subscribe();
    app.stream_cursor.send_replace(Some(cursor));
    let frames = async_stream::stream! {
        loop {
            let (revisions, next) = app.engine.changes_since(cursor).expect("change log");
            if let Some(last) = revisions.last() {
                cursor = next;
                let hint = StreamEvent::Topic { topic: last.topic, revision: last.revision, cursor };
                yield Ok::<_,Infallible>(Event::default().json_data(hint).expect("serialize hint"));
            }
            match events.recv().await {
                Ok(_) | Err(broadcast::error::RecvError::Lagged(_)) => continue,
                Err(broadcast::error::RecvError::Closed) => break,
            }
        }
    };
    Sse::new(frames)
        .keep_alive(axum::response::sse::KeepAlive::new().interval(Duration::from_secs(1)))
        .into_response()
}

fn info(c: Connection) -> ConnectionInfo {
    ConnectionInfo {
        unrouted: c.unrouted,
        health: match c.health {
            Health::Ok { .. } => "ok",
            Health::Expired { .. } => "expired",
            Health::Failing { .. } => "failing",
        }
        .into(),
        unhealthy_since: match c.health {
            Health::Ok { .. } => None,
            Health::Expired { since, .. } | Health::Failing { since, .. } => Some(since),
        },
        summary: c.health.summary().into(),
        account: Some(c.account),
        grants: c.grants,
        id: c.id,
        kind: c.kind,
        label: c.label,
    }
}

async fn connections(State(app): State<Arc<App>>) -> Json<Connections> {
    Json(Connections {
        connections: app
            .engine
            .connections()
            .expect("connections")
            .into_iter()
            .map(info)
            .collect(),
    })
}

async fn put_connection(
    State(app): State<Arc<App>>,
    Path(id): Path<String>,
    Json(grant): Json<ConnectionGrant>,
) -> Json<ConnectionInfo> {
    let c = Connection {
        unrouted: 0,
        id,
        kind: grant.kind,
        label: grant.label,
        account: grant.account.unwrap_or_default(),
        grants: grant.grants,
        health: Health::Ok {
            checked_at: Utc::now(),
        },
    };
    app.engine
        .add_connection(c.clone())
        .expect("new connection");
    Json(info(c))
}

fn file_response(blob: meep_engine::Blob) -> Response {
    let mut response = blob.bytes.into_response();
    response
        .headers_mut()
        .insert("x-meep-revision", HeaderValue::from(blob.revision));
    response
}

async fn get_file(
    State(app): State<Arc<App>>,
    Path((topic, path)): Path<(TopicId, String)>,
    axum::extract::Query(query): axum::extract::Query<std::collections::HashMap<String, u64>>,
) -> Response {
    match app
        .engine
        .blobs()
        .get(topic, &path, query.get("revision").copied())
        .expect("read blob")
    {
        Some(blob) => file_response(blob),
        None => error(StatusCode::NOT_FOUND, "missing_file", "no such file"),
    }
}

async fn put_file(
    State(app): State<Arc<App>>,
    Path((topic, path)): Path<(TopicId, String)>,
    headers: axum::http::HeaderMap,
    bytes: Bytes,
) -> Response {
    if app.reject_upload.load(SeqCst) {
        return error(StatusCode::CONFLICT, "conflict", "File is read-only");
    }
    let key = headers
        .get("idempotency-key")
        .and_then(|v| v.to_str().ok()?.parse().ok())
        .unwrap_or_else(uuid::Uuid::new_v4);
    let base = headers
        .get("x-meep-base-revision")
        .map(|v| v.to_str().unwrap().parse().unwrap());
    let write = app
        .engine
        .write_file(topic, path, bytes.to_vec(), key, base)
        .await
        .expect("write blob");
    let mut response = file_response(write.revision);
    if let Some(head) = write.competing_with {
        response
            .headers_mut()
            .insert("x-meep-conflict-head", head.into());
    }
    response
}
