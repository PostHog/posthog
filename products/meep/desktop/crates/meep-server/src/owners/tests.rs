use super::*;
use crate::http;
use meep_topic::{Command, Envelope, TopicId};
use meep_wire::{CommandResult, CommandResults};
use reqwest::{Method, StatusCode};
use serde_json::{Value, json};

async fn response_json(request: reqwest::RequestBuilder) -> Result<Value> {
    Ok(request.send().await?.error_for_status()?.json().await?)
}

struct FixtureStorage {
    root: tempfile::TempDir,
    tokens: Arc<DeviceTokens>,
}
#[async_trait::async_trait]
impl OwnerServices for FixtureStorage {
    fn owners(&self) -> Result<Vec<Uuid>> {
        Ok(self.tokens.owners()?.into_keys().collect())
    }
    async fn open(&self, id: Uuid) -> Result<Server> {
        let root = if id == self.tokens.implicit_owner() {
            self.root.path().to_owned()
        } else {
            self.root.path().join(id.to_string())
        };
        Server::with_storage(
            Arc::new(SqliteStore::open(&root)?),
            Arc::new(DirBlobs::open(root.join("files"))?),
            Arc::new(StoreState::new(meep_store::Connection::open(
                root.join("checkpoints.sqlite"),
            )?)?),
            Box::new(FileSecrets::open(root.join("secrets"))?),
            self.tokens.clone(),
            Arc::new(Connectors),
        )
        .await
        .map(Server::without_topic_setup)
    }
}
struct Fixture {
    storage: Arc<FixtureStorage>,
    host: Arc<Host>,
    origin: String,
    http: reqwest::Client,
    alice: String,
    bob: String,
    bob_id: Uuid,
    listener: tokio::task::JoinHandle<std::io::Result<()>>,
}
impl Fixture {
    async fn new() -> Result<Self> {
        let root = tempfile::tempdir()?;
        let tokens = Arc::new(DeviceTokens::open(root.path())?);
        let storage = Arc::new(FixtureStorage { root, tokens });
        Self::start(storage).await
    }
    async fn start(storage: Arc<FixtureStorage>) -> Result<Self> {
        let id = storage.tokens.implicit_owner();
        let s = storage
            .open(id)
            .await?
            .with_owner_services(storage.clone())
            .with_public_base("https://fixture.invalid")?;
        let host = Host::start(s, CancellationToken::new()).await?;
        // Provision the second owner with the service already running.
        let bob_id = storage.tokens.add_owner(Some("Bob".into()))?;
        let bob = storage.tokens.create_for(bob_id)?;
        let alice = storage.tokens.create()?;
        let socket = TcpListener::bind("127.0.0.1:0").await?;
        let origin = format!("http://{}", socket.local_addr()?);
        let app = http::router(host.clone());
        let stop = host.stop.clone();
        let listener = tokio::spawn(async move {
            axum::serve(socket, app)
                .with_graceful_shutdown(stop.cancelled_owned())
                .await
        });
        Ok(Self {
            storage,
            host,
            origin,
            http: reqwest::Client::new(),
            alice,
            bob,
            bob_id,
            listener,
        })
    }
    fn request(&self, token: &str, method: Method, path: &str) -> reqwest::RequestBuilder {
        self.http
            .request(method, format!("{}/v1/{path}", self.origin))
            .bearer_auth(token)
    }
    async fn get(&self, token: &str, path: &str) -> Result<Value> {
        response_json(self.request(token, Method::GET, path)).await
    }
    async fn command(
        &self,
        token: &str,
        id: Uuid,
        topic: TopicId,
        command: Command,
    ) -> Result<CommandResult> {
        let envelope = Envelope {
            id: id.into(),
            topic,
            issued_at: Utc::now(),
            command,
        };
        let result: CommandResults = self
            .request(token, Method::POST, "commands")
            .json(&json!({"commands":[envelope]}))
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        Ok(result.results.into_iter().next().unwrap())
    }
    async fn seed(&self, token: &str, id: Uuid, topic: TopicId, name: &str) -> Result<()> {
        assert!(matches!(
            self.command(
                token,
                id,
                topic,
                Command::CreateTopic {
                    name: name.into(),
                    mission: format!("{name} private mission")
                }
            )
            .await?,
            CommandResult::Applied { .. }
        ));
        self.request(token, Method::PUT, &format!("topics/{topic}/files/summary"))
            .body(name.to_owned())
            .send()
            .await?
            .error_for_status()?;
        Ok(())
    }
    async fn close(self) -> Result<()> {
        self.host.stop.cancel();
        self.listener.await??;
        self.host.shutdown().await;
        Ok(())
    }
}

#[tokio::test]
async fn device_reads_commands_and_references_use_only_the_authenticated_namespace() -> Result<()> {
    let f = Fixture::new().await?;
    let alice: TopicId = Uuid::new_v4().into();
    let bob: TopicId = Uuid::new_v4().into();
    let command = Uuid::new_v4();
    f.seed(&f.alice, command, alice, "Alpine").await?;
    let get = |path: &str| f.request(&f.alice, Method::GET, path);
    let put = |path: &str| f.request(&f.alice, Method::PUT, path);
    let post = |path: &str| f.request(&f.alice, Method::POST, path);
    let snapshot = format!("topics/{bob}");
    let missing = get(&snapshot).send().await?;
    f.seed(&f.bob, command, bob, "Boreal").await?;
    let foreign = get(&snapshot).send().await?;
    assert_eq!(foreign.status(), StatusCode::NOT_FOUND);
    assert_eq!(foreign.status(), missing.status());
    assert_eq!(foreign.bytes().await?, missing.bytes().await?);
    let (foreign_view, own_view) = (Uuid::new_v4(), Uuid::new_v4());
    let view_command =
        |view, command| json!({"id":Uuid::new_v4(),"view":view,"at":Utc::now(),"command":command});
    for (token, id, name) in [
        (&f.bob, foreign_view, "Boreal"),
        (&f.alice, own_view, "Alpine"),
    ] {
        let create = view_command(id, json!({"kind":"create","prompt":name}));
        response_json(
            f.request(token, Method::POST, "views/commands")
                .json(&create),
        )
        .await?;
    }
    for route in [
        "changes?limit=1",
        "changes",
        "search?q=Boreal",
        "needs-you",
        "sources",
        "connections",
        "views",
        "routine-templates",
    ] {
        let data = f.get(&f.alice, route).await?.to_string();
        assert!(
            !data.contains("Boreal")
                && !data.contains(&bob.to_string())
                && !data.contains(&foreign_view.to_string()),
            "{route}"
        );
    }
    use std::sync::atomic::{AtomicUsize, Ordering};
    let calls = Arc::new(AtomicUsize::new(0));
    let count = calls.clone();
    let models = axum::routing::get(move || async move {
        count.fetch_add(1, Ordering::SeqCst);
        axum::Json(json!({"models":[]}))
    });
    let provider = axum::Router::new()
        .route("/api/projects/7/tasks/models/", models)
        .fallback(|| async { axum::Json(json!({"results":[]})) });
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let region = format!("http://{}", listener.local_addr()?);
    let mock = tokio::spawn(async move { axum::serve(listener, provider).await });
    let grant = json!({"kind":"posthog","label":"Bob provider","grants":[bob],
                       "secrets":{"access_token":"provider-bob","project_id":"7","region":region}});
    response_json(
        f.request(&f.bob, Method::PUT, "connections/posthog")
            .json(&grant),
    )
    .await?;
    let files = format!("{snapshot}/files");
    let models = format!("{snapshot}/models");
    let routine = format!("routines/{bob}/weekly");
    let delete = view_command(foreign_view, json!({"kind":"delete"}));
    let read = json!({"source":"topics","tool":"file","arguments":{"topic":bob,"path":"summary"}});
    for request in [
        get(&format!("sources?topic={bob}")),
        get(&files),
        get(&format!("{files}/summary?revision=1")),
        put(&format!("{files}/summary")).body("overwrite"),
        get(&models),
        put(&models).json(&json!({"model":"private"})),
        post(&format!("{snapshot}/routines")).json(&json!({"template":"urgent-only"})),
        get(&routine),
        put(&routine).json(&json!({"flow_id":"1","enabled":true})),
        put(&format!("connections/posthog/topics/{bob}")),
        put("connections/posthog/ai-key").json(&json!({"key":"test"})),
        put("connections/build").json(&json!({"kind":"webhook","label":"test","grants":[bob]})),
        post("connections/posthog/mcp-store").json(&json!({"action":"browse"})),
        post("views/commands").json(&delete),
        post(&format!("views/{foreign_view}/sources")).json(&read),
        post(&format!("views/{own_view}/sources")).json(&read),
    ] {
        let response = request.send().await?;
        assert_eq!(
            response.status(),
            StatusCode::NOT_FOUND,
            "{}",
            response.url()
        );
    }
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    mock.abort();
    assert!(matches!(
        f.command(
            &f.alice,
            Uuid::new_v4(),
            bob,
            Command::SetMission {
                mission: "overwrite".into()
            }
        )
        .await?,
        CommandResult::Rejected { .. }
    ));
    assert_eq!(
        f.get(&f.bob, &format!("topics/{bob}")).await?["state"]["topic"]["mission"],
        "Boreal private mission"
    );
    f.close().await
}

#[tokio::test]
async fn two_owners_can_reuse_identifiers_and_deliver_events_independently() -> Result<()> {
    let f = Fixture::new().await?;
    let topic: TopicId = Uuid::new_v4().into();
    let bob = f.host.service(f.bob_id).await?.unwrap();
    let mut callbacks = vec![];
    let command = Uuid::new_v4();
    for (s, token, label) in [(&f.host.implicit, &f.alice, "Alice"), (&bob, &f.bob, "Bob")] {
        f.seed(token, command, topic, label).await?;
        let watch = meep_topic::Watch {
            id: Uuid::new_v4().into(),
            connection: "build".into(),
            kind: "project".into(),
            key: "desktop".into(),
            label: "Build".into(),
        };
        s.engine.set_watch(topic, vec![watch.clone()]).await?;
        let config = json!({"watch":watch,"auth":{"kind":"shared_secret","header":"x-build-token"},"mapping":{"id":"/id","author":"/actor","timestamp":"/at","text":"/text"}});
        f.request(token,Method::PUT,"connections/build").json(&json!({"kind":"webhook","label":label,"grants":[topic],"secrets":{"webhook_secret":label,"config":config.to_string()}})).send().await?.error_for_status()?;
        let callback = s
            .engine
            .bind_routine(
                topic,
                meep_topic::RoutineBinding {
                    id: "weekly".into(),
                    name: "Weekly".into(),
                    trigger: "Manual".into(),
                    backend: "posthog".into(),
                    external_id: Uuid::new_v4().to_string(),
                    watches: vec![],
                },
            )
            .await?;
        callbacks.push(callback);
        s.accounts
            .checkpoints
            .commit(&format!("chat-model/{topic}"), None, &json!(label))?;
    }
    let implicit = f.host.implicit.owner;
    let bob_id = f.bob_id;
    let webhook = |owner, secret, label| {
        f.http
            .post(format!("{}/owners/{owner}/v1/ingest/build", f.origin))
            .header("x-build-token", secret)
            .json(&json!({"id":"same-event","actor":"CI","at":Utc::now(),"text":label}))
    };
    assert_eq!(
        webhook(bob_id, "Alice", "cross-owner")
            .send()
            .await?
            .status(),
        401
    );
    for (id, key) in [(implicit, "Alice"), (bob_id, "Bob")] {
        for _ in 0..2 {
            webhook(id, key, key).send().await?.error_for_status()?;
        }
    }
    let effect = Uuid::new_v4();
    let callback = |prefix: &str, key: &str| {
        f.http
            .post(format!(
                "{}{prefix}/v1/routines/{topic}/weekly/callback",
                f.origin
            ))
            .header("Idempotency-Key", effect.to_string())
            .json(&json!({"secret":key,"op":{"kind":"AddFact","text":"from routine"}}))
    };
    assert_eq!(
        callback(&format!("/owners/{bob_id}"), &callbacks[0])
            .send()
            .await?
            .status(),
        401
    );
    callback("", &callbacks[0])
        .send()
        .await?
        .error_for_status()?;
    callback(&format!("/owners/{bob_id}"), &callbacks[1])
        .send()
        .await?
        .error_for_status()?;
    let paired = f.storage.tokens.create()?;
    let path = format!("topics/{topic}/files/summary");
    for (s, token, label) in [(&f.host.implicit, &paired, "Alice"), (&bob, &f.bob, "Bob")] {
        assert_eq!(
            f.request(token, Method::GET, &path)
                .send()
                .await?
                .text()
                .await?,
            label
        );
        assert_eq!(s.accounts.chat_model(topic)?.as_deref(), Some(label));
        let state = s.engine.topic(topic)?;
        assert_eq!(state.topic.facts.len(), 1);
        let observations = s.engine.source_observations(topic, 2)?;
        assert_eq!(observations.len(), 1);
        assert_eq!(observations[0]["text"], label);
        assert_eq!(
            state.topic.fallback.observations[0].outcome,
            meep_topic::ObservationOutcome::Finished {
                reason: "Recorded source observation".into(),
            }
        );
        assert!(state.threads.iter().all(|thread| !thread.is_agent_report()));
        assert!(state.threads.iter().all(|thread| !thread.source_material));
        assert!(state.needs_you().threads.is_empty());
        let capability = crate::topic_mcp::Capability::issue(&s.accounts, topic, "build")
            .context("owner-scoped agent capability")?;
        let prefix = if label == "Alice" {
            String::new()
        } else {
            format!("/owners/{bob_id}")
        };
        let inbox = response_json(
            f.http
                .post(format!("{}{prefix}/v1/topics/{topic}/mcp", f.origin))
                .bearer_auth(&capability.token)
                .json(&json!({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_threads","arguments":{}}})),
        )
        .await?;
        assert_ne!(inbox["result"]["isError"], true);
        let reports: Value = serde_json::from_str(
            inbox["result"]["content"][0]["text"]
                .as_str()
                .context("report list")?,
        )?;
        assert_eq!(
            reports,
            json!([]),
            "source intake must not publish an inbox report"
        );
    }
    f.close().await
}

#[tokio::test]
async fn both_mcp_catalogs_and_explicit_tool_reads_are_scoped_to_the_run() -> Result<()> {
    use sha2::{Digest, Sha256};
    let f = Fixture::new().await?;
    let a: TopicId = Uuid::new_v4().into();
    let b: TopicId = Uuid::new_v4().into();
    f.seed(&f.alice, Uuid::new_v4(), a, "Alpine").await?;
    f.seed(&f.bob, Uuid::new_v4(), b, "Boreal").await?;
    let s = f.host.service(f.bob_id).await?.unwrap();
    assert!(
        s.engine
            .send_to_topic(b, a, "cross-owner", 0)
            .await
            .is_err()
    );
    let local = Uuid::new_v4().into();
    f.seed(&f.bob, Uuid::new_v4(), local, "LocalPeer").await?;
    let grant = json!({"kind":"webhook","label":"Build","grants":[b,local],"secrets":{"webhook_secret":"fixture"}});
    response_json(
        f.request(&f.bob, Method::PUT, "connections/build")
            .json(&grant),
    )
    .await?;
    let mentions = s
        .accounts
        .mentioned_context("build", b, "Compare @LocalPeer and @Alpine")?;
    assert!(mentions.contains("LocalPeer private mission"));
    assert!(!mentions.contains("Alpine"));
    let capability = crate::topic_mcp::Capability::issue(&s.accounts, b, "build").unwrap();
    let path = format!("/owners/{}/v1/topics/{b}/mcp", f.bob_id);
    assert!(capability.url.ends_with(&path));
    let mcp = |path: &str, token: &str, name: &str, args: Value| {
        f.http.post(format!("{}{path}",f.origin)).bearer_auth(token)
        .json(&json!({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":name,"arguments":args}}))
    };
    let list = response_json(mcp(&path, &capability.token, "list_topics", json!({}))).await?;
    let catalog = list.to_string();
    assert!(catalog.contains("Boreal") && !catalog.contains("Alpine"));
    let read = response_json(mcp(
        &path,
        &capability.token,
        "get_topic",
        json!({"topic":a}),
    ))
    .await?;
    assert_eq!(read["result"]["isError"], true);
    let wrong = format!("/v1/topics/{b}/mcp");
    assert_eq!(
        mcp(&wrong, &capability.token, "list_topics", json!({}))
            .send()
            .await?
            .status(),
        401
    );

    // Seed the same durable capability field an active authoring turn uses.
    let view = Uuid::new_v4();
    s.views.command(meep_wire::views::ViewEnvelope {
        id: Uuid::new_v4(),
        at: Utc::now(),
        view,
        command: meep_wire::views::ViewCommand::Create {
            prompt: "Design".into(),
            options: Default::default(),
        },
    })?;
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while s.views.read(view)?.pending().is_some() {
            tokio::task::yield_now().await;
        }
        anyhow::Ok(())
    })
    .await??;
    let token = Uuid::new_v4().to_string();
    s.views.update(view, |r| {
        r.capability = Some(format!("{:x}", Sha256::digest(&token)));
        Ok(())
    })?;
    let path = format!("/owners/{}/v1/views/{view}/mcp", f.bob_id);
    let list = response_json(mcp(&path, &token, "list_sources", json!({}))).await?;
    let catalog = list.to_string();
    assert!(catalog.contains("Boreal") && !catalog.contains("Alpine"));
    for (topic, denied) in [(a, true), (b, false)] {
        let args =
            json!({"source":"topics","tool":"file","arguments":{"topic":topic,"path":"summary"}});
        let result = response_json(mcp(&path, &token, "read_source", args)).await?;
        assert_eq!(result["result"]["isError"], denied);
    }
    f.close().await
}

#[tokio::test]
async fn stream_resumption_and_revocation_use_only_the_subscribing_owner() -> Result<()> {
    use futures_util::StreamExt;
    use meep_client::{HttpTransport, Transport};
    use meep_wire::StreamEvent;
    use sha2::{Digest, Sha256};
    use std::time::Duration;
    let f = Fixture::new().await?;
    let topic = Uuid::new_v4().into();
    f.seed(&f.alice, Uuid::new_v4(), topic, "Alpine").await?;
    let cursor = f.get(&f.alice, "health").await?["cursor"].as_u64().unwrap();
    let transport = HttpTransport::new(&f.origin, &f.alice)?;
    let mut stream = transport.stream(cursor).await?;
    let bob = f.host.service(f.bob_id).await?.unwrap();
    f.seed(&f.bob, Uuid::new_v4(), Uuid::new_v4().into(), "Boreal")
        .await?;
    let info = meep_connections::Connection {
        unrouted: 0,
        id: "private".into(),
        label: "Boreal".into(),
        account: String::new(),
        kind: "webhook".into(),
        grants: vec![],
        health: meep_connections::Health::Ok {
            checked_at: Utc::now(),
        },
    };
    // Overrun Bob's connection broadcast buffer while Alice's stream is open.
    for _ in 0..256 {
        let _ = bob.accounts.feed.send(crate::accounts::info(&info));
    }
    let _ = bob.views.feed.send(());
    assert_eq!(f.get(&f.alice, "health").await?["cursor"], cursor);
    f.command(
        &f.alice,
        Uuid::new_v4(),
        topic,
        Command::SetMission {
            mission: "Changed".into(),
        },
    )
    .await?;
    let seen = tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            match stream.next().await.context("stream closed")?? {
                StreamEvent::Heartbeat { .. } => (),
                StreamEvent::Topic {
                    topic: changed,
                    cursor,
                    ..
                } => {
                    assert_eq!(changed, topic);
                    return anyhow::Ok(cursor);
                }
                other => anyhow::bail!("unexpected foreign event: {other:?}"),
            }
        }
    })
    .await??;
    assert_eq!(seen, cursor + 1);
    drop(stream);
    let mut resumed = transport.stream(seen).await?;
    let fingerprint = format!("{:x}", Sha256::digest(&f.alice));
    f.storage.tokens.revoke(&fingerprint[..16])?;
    let same_owner = f.storage.tokens.create()?;
    f.command(
        &same_owner,
        Uuid::new_v4(),
        topic,
        Command::SetMission {
            mission: "After revoke".into(),
        },
    )
    .await?;
    tokio::time::timeout(Duration::from_secs(5), async {
        while let Some(event) = resumed.next().await {
            assert!(matches!(event?, StreamEvent::Heartbeat { .. }));
        }
        anyhow::Ok(())
    })
    .await??;
    assert_eq!(
        f.request(&f.alice, Method::GET, "health")
            .send()
            .await?
            .status(),
        401
    );
    f.close().await
}
