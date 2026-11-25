use super::*;
use axum::response::{Sse, sse::Event};
use std::{collections::BTreeSet, time::Duration};
use tokio::sync::broadcast;

#[derive(Serialize, Deserialize, Default)]
pub(super) struct Position {
    replica: Option<uuid::Uuid>,
    #[serde(default)]
    bootstrap: bool,
    #[serde(default)]
    cursor: u64,
    limit: Option<usize>,
}

pub(super) async fn changes(
    Extension(a): Extension<App>,
    Query(q): Query<Position>,
) -> Result<Response> {
    let limit = q.limit.unwrap_or(PAGE).clamp(1, PAGE);
    let store = a.s.accounts.store.clone();
    let mut rows = tokio::task::spawn_blocking(move || {
        if q.bootstrap {
            store.bootstrap_page(q.cursor, limit + 1)
        } else {
            store.revision_page(q.cursor, limit + 1)
        }
    })
    .await
    .map_err(Failure::internal)?
    .map_err(Failure::internal)?;
    let more = rows.len() > limit;
    rows.truncate(limit);
    let cursor = rows.last().map_or(q.cursor, |r| r.0);
    let mut seen = BTreeSet::new();
    let mut topics = vec![];
    for (_, r) in rows {
        if seen.insert(r.topic) {
            topics.push(if let Some(replica) = q.replica {
                a.s.engine.replica_snapshot(r.topic, replica).await?
            } else {
                let engine = a.s.engine.clone();
                tokio::task::spawn_blocking(move || engine.snapshot(r.topic))
                    .await
                    .map_err(Failure::internal)??
            });
        }
    }
    tokio::task::spawn_blocking(move || {
        Json(ChangePage {
            topics,
            cursor,
            more,
        })
        .into_response()
    })
    .await
    .map_err(Failure::internal)
}

pub(super) async fn ack_deletions(
    Extension(a): Extension<App>,
    Json(ack): Json<DeletionAck>,
) -> Result<Json<()>> {
    for (topic, revision) in ack.topics {
        a.s.engine
            .acknowledge_deletion(topic, revision, ack.replica)
            .await?;
    }
    Ok(Json(()))
}

pub(super) async fn snapshot(
    Extension(a): Extension<App>,
    Path(id): Path<TopicId>,
) -> Result<Response> {
    tokio::task::spawn_blocking(move || Ok(Json(a.s.engine.snapshot(id)?).into_response()))
        .await
        .map_err(Failure::internal)?
}

pub(super) async fn stream(
    Extension(a): Extension<App>,
    Query(q): Query<Position>,
    headers: HeaderMap,
) -> Result<Response> {
    let last = headers
        .get("last-event-id")
        .map(|v| {
            v.to_str()
                .ok()
                .and_then(|s| s.parse::<u64>().ok())
                .ok_or_else(|| Failure::bad("Invalid Last-Event-ID"))
        })
        .transpose()?;
    let token = bearer(&headers)?.to_owned();
    let mut cursor = q.cursor.max(last.unwrap_or_default());
    let mut wake = a.s.engine.subscribe();
    let mut accounts = a.s.accounts.feed.subscribe();
    let mut views = a.s.views.feed.subscribe();
    let out = async_stream::try_stream! {
        let mut heartbeat=tokio::time::interval(Duration::from_secs(15));
        heartbeat.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        'stream: loop {
            if a.stop.is_cancelled() {break;}
            let store = a.s.accounts.store.clone();
            let rows=tokio::task::spawn_blocking(move || store.revision_page(cursor,PAGE)).await.map_err(std::io::Error::other)?.map_err(std::io::Error::other)?;
            let full=rows.len()==PAGE;
            for (position,r) in rows {
                if device_owner(a.s.auth.clone(), token.clone()).await.map_err(std::io::Error::other)? != Some(a.s.owner) { break 'stream; }
                cursor=position;
                let data=StreamEvent::Topic{topic:r.topic,revision:r.revision,cursor};
                yield Event::default().id(cursor.to_string()).json_data(data).map_err(std::io::Error::other)?;
            }
            if full {continue}
            let notice = tokio::select! {
                _=a.stop.cancelled()=>break,
                _=heartbeat.tick()=>Ok(vec![StreamEvent::Heartbeat{at:Utc::now()}]),
                result=accounts.recv()=>match result {
                    Ok(c)=>Ok(vec![StreamEvent::Connection(c)]),
                    Err(broadcast::error::RecvError::Lagged(_)) => {
                        // Subscribe before reading the snapshot. Buffered pre-snapshot
                        // notifications must never rewind an account after resync.
                        accounts = accounts.resubscribe();
                        a.s.accounts.store.connections().map(|cs| cs.iter().map(|c| StreamEvent::Connection(info(c))).collect())
                    }
                    Err(broadcast::error::RecvError::Closed)=>break,
                },
                _=wake.recv()=>continue,
                _=views.recv()=>Ok(vec![StreamEvent::Views]),
            };
            for data in notice.map_err(std::io::Error::other)? {
                if device_owner(a.s.auth.clone(), token.clone()).await.map_err(std::io::Error::other)? != Some(a.s.owner) { break 'stream; }
                yield Event::default().json_data(data).map_err(std::io::Error::other)?;
            }
        }
    };
    fn typed(
        stream: impl futures_util::Stream<Item = std::io::Result<Event>>,
    ) -> impl futures_util::Stream<Item = std::io::Result<Event>> {
        stream
    }
    Ok(Sse::new(typed(out)).into_response())
}

#[cfg(test)]
mod tests {
    use super::*;
    use anyhow::Context;
    use futures_util::StreamExt;
    #[tokio::test]
    async fn lagged_connection_stream_resyncs_and_discards_older_buffered_states()
    -> anyhow::Result<()> {
        let dir = tempfile::tempdir()?;
        let s = Server::open(dir.path()).await?;
        let auth = std::fs::read_to_string(dir.path().join("device-token"))?;
        let mut headers = HeaderMap::new();
        headers.insert(header::AUTHORIZATION, format!("Bearer {auth}").parse()?);
        let public = meep_connections::Connection {
            unrouted: 0,
            id: "builds".into(),
            kind: "webhook".into(),
            label: "Current".into(),
            account: String::new(),
            grants: vec![],
            health: meep_connections::Health::Ok {
                checked_at: Utc::now(),
            },
        };
        s.engine.add_connection(public.clone())?;
        let response = stream(
            Extension(App {
                s: s.clone(),
                stop: CancellationToken::new(),
            }),
            Query(Position {
                replica: None,
                bootstrap: false,
                cursor: 0,
                limit: None,
            }),
            headers,
        )
        .await
        .expect("fixture authorization");
        let mut body = response.into_body().into_data_stream();
        let mut old = info(&public);
        old.label = "Superseded".into();
        for _ in 0..256 {
            s.accounts.feed.send(old.clone())?;
        }
        let read_connection = |bytes: &[u8]| -> anyhow::Result<Option<String>> {
            for line in std::str::from_utf8(bytes)?.lines() {
                if let Some(data) = line.strip_prefix("data:")
                    && let StreamEvent::Connection(account) = serde_json::from_str(data)?
                {
                    return Ok(Some(account.label));
                }
            }
            Ok(None)
        };
        let mut first = true;
        tokio::time::timeout(Duration::from_secs(2), async {
            while let Some(bytes) = body.next().await {
                if let Some(label) = read_connection(&bytes?)? {
                    if first {
                        assert_eq!(label, "Current");
                        first = false;
                        let mut next = info(&public);
                        next.label = "Next".into();
                        s.accounts.feed.send(next)?;
                    } else {
                        assert_eq!(label, "Next");
                        return anyhow::Ok(());
                    }
                }
            }
            None.context("connection stream closed")
        })
        .await??;
        Ok(())
    }
}
