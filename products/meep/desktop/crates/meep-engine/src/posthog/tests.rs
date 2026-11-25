use super::*;
use crate::{Engine, FixtureSorter, ManualClock};
use chrono::{DateTime, TimeDelta};
use meep_policy::Limits;
use meep_topic::{Fact, Provenance, Rule, RuleEffect};
use serde_json::Value;
use std::{sync::Arc, time::Duration};
use tiny_http::{Header, Response, Server};

#[tokio::test]
async fn uncertain_manual_run_survives_health_checks_and_restart_until_acknowledged() -> Result<()>
{
    use crate::{
        DispatchUncertain, MemoryBlobs, MemoryStore, RoutineBackend, RoutineContext, RoutineRun,
    };
    use meep_topic::{Command, CommandId, RoutineBinding, RoutineHealth};
    use std::sync::atomic::{AtomicUsize, Ordering};
    struct Uncertain(AtomicUsize);
    #[async_trait::async_trait]
    impl RoutineBackend for Uncertain {
        fn name(&self) -> &str {
            "fixture"
        }
        fn bind(&self, _: &RoutineBinding) -> Result<()> {
            Ok(())
        }
        async fn start(
            &self,
            _: RoutineContext<'_>,
            _: serde_json::Map<String, Value>,
            _: Uuid,
        ) -> Result<RoutineRun> {
            self.0.fetch_add(1, Ordering::SeqCst);
            Err(DispatchUncertain.into())
        }
        async fn status(&self, _: RoutineContext<'_>, _: Uuid) -> Result<RoutineRun> {
            anyhow::bail!("no receipt")
        }
        async fn health(&self, _: RoutineContext<'_>) -> Result<RoutineHealth> {
            Ok(RoutineHealth::Ok)
        }
    }
    let store = Arc::new(MemoryStore::default());
    let blobs = Arc::new(MemoryBlobs::default());
    let backend = Arc::new(Uncertain(AtomicUsize::new(0)));
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let make = || {
        Engine::with_backends(
            store.clone(),
            blobs.clone(),
            vec![backend.clone()],
            Limits {
                max_hops: 2,
                max_runs_per_hour: 4,
            },
            Arc::new(crate::FixtureAgent::default()),
            Arc::new(FixtureSorter),
            clock.clone(),
        )
    };
    let e = make().await?;
    let (topic, _) = e.create_topic("Fixture", "").await?;
    let binding = RoutineBinding {
        id: "manual".into(),
        name: "Manual".into(),
        trigger: "Manual".into(),
        backend: "fixture".into(),
        external_id: "fixture".into(),
        watches: vec![],
    };
    e.bind_routine(topic, binding.clone()).await?;
    let key = Uuid::new_v4();
    assert!(
        e.start_routine(topic, "manual", Default::default(), key)
            .await
            .is_err()
    );
    assert_eq!(backend.0.load(Ordering::SeqCst), 1);
    clock.advance(TimeDelta::seconds(31));
    e.tick_topic(topic).await?;
    assert_eq!(backend.0.load(Ordering::SeqCst), 1);
    e.routine_health(topic, "manual").await?;
    assert_eq!(
        e.topic(topic)?.topic.routines[0].uncertain_manual_run,
        Some(CommandId(key))
    );
    drop(e);
    let restored = make().await?;
    assert_eq!(
        restored.topic(topic)?.topic.routines[0].uncertain_manual_run,
        Some(CommandId(key))
    );
    let mut rebound = binding;
    rebound.name = "Renamed".into();
    restored.bind_routine(topic, rebound).await?;
    assert_eq!(
        restored.topic(topic)?.topic.routines[0].uncertain_manual_run,
        Some(CommandId(key))
    );
    assert!(
        restored
            .start_routine(topic, "manual", Default::default(), Uuid::new_v4())
            .await
            .is_err()
    );
    assert!(
        restored
            .command(
                topic,
                Command::AcknowledgeRoutineDispatch {
                    routine: "manual".into(),
                    expected: CommandId(Uuid::new_v4())
                }
            )
            .await
            .is_err()
    );
    assert_eq!(backend.0.load(Ordering::SeqCst), 1);
    restored
        .command(
            topic,
            Command::AcknowledgeRoutineDispatch {
                routine: "manual".into(),
                expected: CommandId(key),
            },
        )
        .await?;
    assert_eq!(
        restored.topic(topic)?.topic.routines[0].uncertain_manual_run,
        None
    );
    assert!(
        restored
            .start_routine(topic, "manual", Default::default(), Uuid::new_v4())
            .await
            .is_err()
    );
    assert_eq!(backend.0.load(Ordering::SeqCst), 2);
    Ok(())
}

#[tokio::test]
async fn observation_only_sorter_rejects_manual_dispatch_before_provider_request() -> Result<()> {
    use crate::{MemoryBlobs, MemoryStore, PostHogRoutines};
    use meep_topic::RoutineBinding;
    let e = Engine::with_backends(
        Arc::new(MemoryStore::default()),
        Arc::new(MemoryBlobs::default()),
        vec![Arc::new(PostHogRoutines::new(
            "http://127.0.0.1:1",
            9,
            "fixture",
        )?)],
        Limits {
            max_hops: 2,
            max_runs_per_hour: 4,
        },
        Arc::new(crate::FixtureAgent::default()),
        Arc::new(FixtureSorter),
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await?;
    let (topic, _) = e.create_topic("Fixture", "").await?;
    let binding = RoutineBinding {
        id: "sort".into(),
        name: "Sort".into(),
        trigger: "Source event".into(),
        backend: "posthog".into(),
        external_id: Uuid::new_v4().to_string(),
        watches: vec![],
    };
    e.bind_routine(topic, binding.clone()).await?;
    assert!(e.manual_run_allowed(topic, &binding)?);
    e.configure_source_sort(topic, &binding, true).await?;
    assert!(!e.manual_run_allowed(topic, &binding)?);
    let mut stale = binding.clone();
    stale.external_id = Uuid::new_v4().to_string();
    assert!(e.manual_run_allowed(topic, &stale).is_err());
    let message = "requires a source observation";
    assert!(
        e.start_routine(topic, "sort", Default::default(), Uuid::new_v4())
            .await
            .unwrap_err()
            .to_string()
            .contains(message)
    );
    assert!(
        e.request_routine_run(topic, "sort", Default::default())
            .await
            .unwrap_err()
            .to_string()
            .contains(message)
    );
    assert!(e.topic(topic)?.tasks.is_empty());
    Ok(())
}

#[tokio::test]
async fn observation_lookup_requires_one_complete_unique_match() -> Result<()> {
    use crate::{PostHogRoutines, RoutineBackend, RoutineContext};
    for case in [
        "missing",
        "match",
        "large",
        "other",
        "duplicate",
        "partial_match",
        "incomplete",
        "full",
        "paged",
        "truncated",
        "count_changed",
        "count_unavailable",
        "swapped",
        "count_final_changed",
    ] {
        let server = Server::http("127.0.0.1:0").map_err(anyhow::Error::from_boxed)?;
        let origin = format!("http://{}", server.server_addr());
        let flow = Uuid::new_v4();
        let observation = Uuid::new_v4();
        let ids: Vec<_> = (0..match case {
            "missing" => 0,
            "duplicate" | "partial_match" => 2,
            "full" => 100,
            "large" => 60,
            _ => 1,
        })
            .map(|_| Uuid::new_v4())
            .collect();
        let expected = ids.first().copied();
        let worker = std::thread::spawn(move || -> Result<()> {
            let request = server
                .recv_timeout(Duration::from_secs(30))?
                .context("initial count request")?;
            assert!(
                request
                    .url()
                    .contains("invocation_results_count/?after=1970-01-01")
            );
            if case == "count_unavailable" {
                request.respond(Response::from_string("{}").with_status_code(404))?;
                return Ok(());
            }
            let count = if case == "truncated" { 2 } else { ids.len() };
            request.respond(Response::from_string(json!({"count":count}).to_string()))?;
            if case == "full" {
                return Ok(());
            }
            let request = server
                .recv_timeout(Duration::from_secs(30))?
                .context("history request")?;
            assert!(request.url().contains("invocation_results/?limit=100"));
            assert!(request.url().contains("after=1970-01-01"));
            let list = json!(
                ids.iter()
                    .map(|id| json!({"invocation_id":id,"status":"failed"}))
                    .collect::<Vec<_>>()
            );
            let verification = list.clone();
            let response = if case == "paged" {
                json!({"results":list,"next":"more"})
            } else {
                list
            };
            request.respond(Response::from_string(response.to_string()))?;
            if case == "paged" || case == "truncated" {
                return Ok(());
            }
            let request = server
                .recv_timeout(Duration::from_secs(30))?
                .context("final count request")?;
            assert!(
                request
                    .url()
                    .contains("invocation_results_count/?after=1970-01-01")
            );
            let count = if case == "count_changed" {
                ids.len() + 1
            } else {
                ids.len()
            };
            request.respond(Response::from_string(json!({"count":count}).to_string()))?;
            if case != "count_changed" {
                let mut remaining: std::collections::HashSet<_> = ids.into_iter().collect();
                while !remaining.is_empty() {
                    let request = server
                        .recv_timeout(Duration::from_secs(30))?
                        .context("detail request")?;
                    let id: Uuid = request
                        .url()
                        .trim_end_matches('/')
                        .rsplit('/')
                        .next()
                        .context("detail ID")?
                        .parse()?;
                    assert!(remaining.remove(&id));
                    let variables = match case {
                        "incomplete" => json!(null),
                        "partial_match" if Some(id) != expected => json!(null),
                        "other" => json!({"observation":Uuid::new_v4()}),
                        "large" if Some(id) != expected => json!({"observation":Uuid::new_v4()}),
                        _ => json!({"observation":observation}),
                    };
                    request.respond(Response::from_string(json!({"invocation_id":id,"status":"failed","invocation_globals":{"variables":variables}}).to_string()))?;
                }
                if matches!(case, "match" | "large" | "swapped" | "count_final_changed") {
                    let request = server
                        .recv_timeout(Duration::from_secs(30))?
                        .context("verification history request")?;
                    assert!(request.url().contains("invocation_results/?limit=100"));
                    let verify = if case == "swapped" {
                        json!([{"invocation_id":Uuid::new_v4(),"status":"failed"}])
                    } else {
                        verification
                    };
                    request.respond(Response::from_string(verify.to_string()))?;
                    if case != "swapped" {
                        let request = server
                            .recv_timeout(Duration::from_secs(30))?
                            .context("completion count request")?;
                        assert!(
                            request
                                .url()
                                .contains("invocation_results_count/?after=1970-01-01")
                        );
                        request.respond(Response::from_string(json!({"count":if case == "count_final_changed" { count+1 } else { count }}).to_string()))?;
                    }
                }
            }
            Ok(())
        });
        let backend = PostHogRoutines::new(&origin, 7, "fixture")?;
        let binding = meep_topic::RoutineBinding {
            id: "flow".into(),
            name: "Flow".into(),
            backend: "posthog".into(),
            trigger: "manual".into(),
            external_id: flow.to_string(),
            watches: vec![],
        };
        let result = backend
            .find_observation(
                RoutineContext {
                    topic: Uuid::new_v4().into(),
                    binding: &binding,
                },
                observation,
            )
            .await;
        if case == "incomplete"
            || case == "partial_match"
            || case == "paged"
            || case == "count_unavailable"
        {
            assert!(result.is_err());
        } else if case == "match" || case == "large" {
            let found = result?.expect("matching observation");
            assert_eq!(Some(found.invocation_id), expected);
            assert_eq!(found.status, "failed");
        } else {
            assert!(result?.is_none(), "{case}");
        }
        worker.join().expect("fixture server")?;
    }
    Ok(())
}

#[tokio::test]
async fn lost_dispatch_connection_is_uncertain() -> Result<()> {
    use crate::{DispatchUncertain, PostHogRoutines, RoutineBackend, RoutineContext};
    use std::io::Read;

    let listener = std::net::TcpListener::bind("127.0.0.1:0")?;
    let origin = format!("http://{}", listener.local_addr()?);
    let worker = std::thread::spawn(move || -> std::io::Result<()> {
        let (mut connection, _) = listener.accept()?;
        let mut request = [0; 4096];
        assert!(connection.read(&mut request)? > 0);
        // The peer closes after receiving the request, without a response.
        Ok(())
    });
    let backend = PostHogRoutines::new(origin, 7, "fixture")?;
    let binding = meep_topic::RoutineBinding {
        id: "flow".into(),
        name: "Flow".into(),
        backend: "posthog".into(),
        trigger: "manual".into(),
        external_id: Uuid::new_v4().to_string(),
        watches: vec![],
    };
    let error = backend
        .start(
            RoutineContext {
                topic: Uuid::new_v4().into(),
                binding: &binding,
            },
            Default::default(),
            Uuid::new_v4(),
        )
        .await
        .unwrap_err();
    assert!(error.is::<DispatchUncertain>());
    worker.join().expect("fixture server")?;
    Ok(())
}

#[tokio::test]
async fn resumed_topic_runs_import_tools_only_for_supported_models() -> Result<()> {
    let server = Server::http("127.0.0.1:0").map_err(anyhow::Error::from_boxed)?;
    let origin = format!("http://{}", server.server_addr());
    let task = Uuid::new_v4();
    let prior = Uuid::new_v4();
    let worker = std::thread::spawn(move || -> Result<()> {
        for (model, expect_tools) in [("claude-haiku-4-5", false), ("claude-sonnet-4-6", true)] {
            let req = server
                .recv_timeout(Duration::from_secs(30))?
                .context("missing run status")?;
            assert_eq!(req.method().as_str(), "GET");
            req.respond(Response::from_string(
                json!({"id":prior,"status":"completed","model":model}).to_string(),
            ))?;
            let mut req = server
                .recv_timeout(Duration::from_secs(30))?
                .context("missing resume")?;
            assert_eq!(req.method().as_str(), "POST");
            let body: Value = serde_json::from_reader(req.as_reader())?;
            assert_eq!(body.get("imported_mcp_servers").is_some(), expect_tools);
            req.respond(Response::from_string(
                json!({"run":{"id":Uuid::new_v4(),"status":"queued"}}).to_string(),
            ))?;
        }
        Ok(())
    });
    let agent = PostHogAgent::new(&origin, 7, "fixture")?;
    let handle = RunHandle(json!([task, prior]));
    for _ in 0..2 {
        agent
            .continue_with_tools(
                &handle,
                "Continue",
                None,
                Some(("https://fixture.test/mcp", "fixture")),
                false,
            )
            .await?;
    }
    worker.join().expect("fixture server")?;
    Ok(())
}

#[tokio::test]
async fn creates_a_cloud_task_with_context_starts_polls_and_reads_the_final_assistant_turn()
-> Result<()> {
    let server = Server::http("127.0.0.1:0").map_err(anyhow::Error::from_boxed)?;
    let origin = format!("http://{}", server.server_addr());
    let task = Uuid::new_v4();
    let run = Uuid::new_v4();
    let mock = std::thread::spawn(move || -> Result<()> {
        let update = |kind: &str, text: &str| json!({"notification":{"method":"session/update","params":{"update":{"sessionUpdate":kind,"content":{"type":"text","text":text}}}}});
        let path = format!("/api/projects/7/tasks/{task}");
        let run_path = format!("{path}/runs/{run}");
        for (method, url, body, more) in [
            (
                "GET",
                "/api/projects/7/tasks/@me/config/".into(),
                json!({"resolved_ai_run_defaults":{"runtime":"acp","runtime_adapter":"claude","model":"claude-sonnet","reasoning_effort":null}}),
                false,
            ),
            (
                "POST",
                "/api/projects/7/tasks/".to_owned(),
                json!({"id":task}),
                false,
            ),
            (
                "POST",
                format!("{path}/run/"),
                json!({"run":{"id":run,"status":"queued"},"run_error":"dispatch response interrupted"}),
                false,
            ),
            (
                "GET",
                format!("{run_path}/"),
                json!({"id":run,"status":"queued"}),
                false,
            ),
            (
                "GET",
                format!("{run_path}/"),
                json!({"id":run,"status":"completed"}),
                false,
            ),
            (
                "GET",
                format!("{run_path}/session_logs/?limit=200&offset=0"),
                json!([update("agent_message_chunk", "Work")]),
                true,
            ),
            (
                "GET",
                format!("{run_path}/session_logs/?limit=200&offset=1"),
                json!([update(
                    "agent_message",
                    &format!(
                        "Earlier answer. Final proposal:\n```json\n{}\n```\nPlease review.",
                        json!({"Submitted":{"action":{"kind":"publish","label":"Publish","done_label":"Published","payload":{}},"result":"Work complete","draft":"For review"}})
                    )
                )]),
                false,
            ),
        ] {
            let mut req = server
                .recv_timeout(Duration::from_secs(30))?
                .context("missing fixture request")?;
            ensure!(
                req.method().as_str() == method && req.url() == url,
                "unexpected request {} {}",
                req.method(),
                req.url()
            );
            ensure!(
                req.headers().iter().any(|h| h.field.equiv("authorization")
                    && h.value.as_str() == "Bearer loopback-fixture"),
                "missing fixture authorization"
            );
            if method == "POST" {
                let request: Value = serde_json::from_reader(req.as_reader())?;
                if url.ends_with("/run/") {
                    assert_eq!(request["mode"], "interactive");
                    assert_eq!(request["model"], "claude-sonnet");
                } else {
                    let description = request["description"].as_str().context("description")?;
                    let (marker, rest) = description.split_once('\n').context("marker line")?;
                    ensure!(
                        marker.starts_with("[meep topic:"),
                        "unattributed task {marker}"
                    );
                    ensure!(
                        rest.starts_with(MEEP_SKILL.trim_end()),
                        "every run carries the Meep skill"
                    );
                    let (_, context) = rest
                        .split_once(&format!("\n{RUN_CONTEXT_HEADING}\n"))
                        .context("run context")?;
                    ensure!(
                        request.get("origin_product").is_none(),
                        "origin sent without configuration"
                    );
                    let context: Value = serde_json::from_str(context)?;
                    assert_eq!(context["mission"], "Understand adoption");
                    assert_eq!(context["task"]["title"], "Report weekly usage");
                    assert_eq!(context["facts"][0]["text"], "212 teams");
                    assert_eq!(context["rules"][0]["text"], "Ask before replying.");
                    assert_eq!(request["start_run"], false);
                }
            }
            let more = Header::from_bytes("x-has-more", if more { "true" } else { "false" })
                .map_err(|()| anyhow::anyhow!("fixture header"))?;
            req.respond(Response::from_string(body.to_string()).with_header(more))?;
        }
        Ok(())
    });
    let clock = Arc::new(ManualClock::new(DateTime::UNIX_EPOCH));
    let engine = Engine::with_clock(
        Arc::new(crate::MemoryStore::default()),
        Limits {
            max_hops: 2,
            max_runs_per_hour: 4,
        },
        Arc::new(PostHogAgent::new(&origin, 7, "loopback-fixture")?),
        Arc::new(FixtureSorter),
        clock.clone(),
    )
    .await?;
    let (topic, _) = engine.create_topic("Canvas", "Understand adoption").await?;
    engine
        .update(topic, &Default::default(), |s, now| {
            let mut changes = s.state.add_fact(
                Fact {
                    id: crate::id(),
                    text: "212 teams".into(),
                    provenance: Provenance {
                        origin: None,
                        author: "Mia".into(),
                        via: "PostHog".into(),
                        at: now,
                        thread: None,
                    },
                    superseded_by: None,
                    invalidated_by: None,
                    withdrawn_at: None,
                },
                now,
            )?;
            changes.extend(s.state.add_rule(
                Rule {
                    id: crate::id(),
                    text: "Ask before replying.".into(),
                    effect: RuleEffect::Ask(meep_topic::ActionKind("reply".into())),
                    from_task: None,
                    created_at: now,
                },
                now,
            )?);
            Ok(changes)
        })
        .await?;
    engine.add_task(topic, "Report weekly usage").await?;
    engine.tick().await?;
    engine.tick().await?;
    assert_eq!(
        engine.topic(topic)?.tasks[0].worker.as_deref(),
        Some("queued")
    );
    clock.advance(TimeDelta::seconds(1));
    engine.tick().await?;
    let state = engine.topic(topic)?;
    assert_eq!(state.tasks[0].column, meep_topic::Column::NeedsYou);
    assert_eq!(state.tasks[0].draft.as_deref(), Some("For review"));
    assert_eq!(state.tasks[0].result.as_deref(), Some("Work complete"));
    mock.join().expect("fixture server")?;
    Ok(())
}

#[tokio::test]
async fn a_bound_flow_dispatches_variables_with_a_stable_key_and_only_callbacks_change_the_board()
-> Result<()> {
    use crate::{MemoryBlobs, MemoryStore, PostHogRoutines, RoutineOp};
    use meep_topic::{RoutineBinding, RoutineHealth};
    let server = Server::http("127.0.0.1:0").map_err(anyhow::Error::from_boxed)?;
    let origin = format!("http://{}", server.server_addr());
    let flow = Uuid::new_v4();
    let key = Uuid::new_v4();
    let invocation = Uuid::new_v4();
    let worker = std::thread::spawn(move || -> Result<()> {
        let root = format!("/api/projects/9/hog_flows/{flow}");
        for (method, path, body) in [
            (
                "POST",
                "run/".into(),
                json!({"detail":"Dispatch temporarily unavailable"}),
            ),
            (
                "POST",
                "run/".into(),
                json!({"invocation_id":invocation,"status":"queued"}),
            ),
            (
                "GET",
                format!("invocation_results/{invocation}/"),
                json!({"invocation_id":invocation,"status":"completed","duration_ms":20}),
            ),
            ("GET", String::new(), json!({"status":"active"})),
        ] {
            let mut req = server
                .recv_timeout(Duration::from_secs(30))?
                .context("missing flow request")?;
            assert_eq!(req.method().as_str(), method);
            assert_eq!(req.url(), format!("{root}/{path}"));
            assert!(
                req.headers().iter().any(|h| h.field.equiv("authorization")
                    && h.value.as_str() == "Bearer loopback-only")
            );
            if method == "POST" {
                assert!(req.headers().iter().any(
                    |h| h.field.equiv("idempotency-key") && h.value.as_str() == key.to_string()
                ));
                let body: Value = serde_json::from_reader(req.as_reader())?;
                assert_eq!(body, json!({"variables":{"week":5}}));
            }
            let status = if body.get("detail").is_some() {
                400
            } else {
                200
            };
            req.respond(Response::from_string(body.to_string()).with_status_code(status))?;
        }
        Ok(())
    });
    let e = Engine::with_backends(
        Arc::new(MemoryStore::default()),
        Arc::new(MemoryBlobs::default()),
        vec![Arc::new(PostHogRoutines::new(origin, 9, "loopback-only")?)],
        Limits {
            max_hops: 2,
            max_runs_per_hour: 4,
        },
        Arc::new(crate::FixtureAgent::default()),
        Arc::new(FixtureSorter),
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await?;
    let (topic, _) = e.create_topic("Rail", "Weekly updates").await?;
    let binding = RoutineBinding {
        watches: vec![],
        id: "weekly".into(),
        name: "Weekly report".into(),
        trigger: "Monday at nine".into(),
        backend: "posthog".into(),
        external_id: flow.to_string(),
    };
    let secret = e.bind_routine(topic, binding.clone()).await?;
    let vars = serde_json::from_value::<serde_json::Map<String, Value>>(json!({"week":5}))?;
    assert!(
        e.start_routine(topic, "weekly", vars.clone(), key)
            .await
            .is_err()
    );
    assert!(matches!(
        e.topic(topic)?.topic.routines[0].health,
        RoutineHealth::Failing(_)
    ));
    for _ in 0..2 {
        assert_eq!(
            e.start_routine(topic, "weekly", vars.clone(), key)
                .await?
                .invocation_id,
            invocation
        );
    }
    assert_eq!(
        e.routine_status(topic, "weekly", invocation).await?.status,
        "completed"
    );
    assert_eq!(e.routine_health(topic, "weekly").await?, RoutineHealth::Ok);
    let state = e.topic(topic)?;
    assert!(state.tasks.is_empty());
    assert_eq!(state.topic.routines[0].binding, binding);
    assert_eq!(state.topic.routines[0].last_run, Some(DateTime::UNIX_EPOCH));
    e.routine_callback(
        topic,
        "weekly",
        &secret,
        RoutineOp::AddTask {
            observation: None,
            title: "Read the report".into(),
            instructions: None,
        },
    )
    .await?;
    assert_eq!(e.topic(topic)?.tasks[0].title, "Read the report");
    worker.join().expect("loopback fixture")?;
    Ok(())
}

#[tokio::test]
async fn view_tasks_are_created_through_the_attributed_path_with_the_configured_origin()
-> Result<()> {
    let server = Server::http("127.0.0.1:0").map_err(anyhow::Error::from_boxed)?;
    let origin = format!("http://{}", server.server_addr());
    let task = Uuid::new_v4();
    let view = Uuid::new_v4();
    let mock = std::thread::spawn(move || -> Result<Value> {
        let mut created = Value::Null;
        for (url, body) in [
            ("/api/projects/7/tasks/".to_owned(), json!({"id":task})),
            // Runs carrying a Meep MCP ask for the account's Claude runtime model.
            (
                "/api/projects/7/tasks/@me/config/".to_owned(),
                json!({"resolved_ai_run_defaults":{"runtime":"acp","runtime_adapter":"claude","model":"claude-test","reasoning_effort":null}}),
            ),
            (
                format!("/api/projects/7/tasks/{task}/run/"),
                json!({"run":{"id":Uuid::new_v4(),"status":"queued"}}),
            ),
        ] {
            let mut req = server
                .recv_timeout(Duration::from_secs(30))?
                .context("missing fixture request")?;
            ensure!(req.url() == url, "unexpected request {}", req.url());
            let request: Value = serde_json::from_reader(req.as_reader()).unwrap_or(Value::Null);
            if created.is_null() {
                created = request;
            }
            req.respond(Response::from_string(body.to_string()))?;
        }
        Ok(created)
    });
    let agent = PostHogAgent::new(&origin, 7, "loopback-fixture")?.with_task_origin(Some("meep"));
    agent
        .author_view(
            view,
            None,
            "Chart signups",
            "https://example.test/mcp",
            "bearer",
            None,
            None,
            vec![],
        )
        .await?;
    let created = mock.join().expect("fixture server")?;
    let description = created["description"].as_str().context("description")?;
    assert!(description.starts_with(&format!("[meep view:{view}]\n{}", MEEP_SKILL.trim_end())));
    assert!(description.ends_with("Chart signups"));
    assert_eq!(created["origin_product"], "meep");
    assert_eq!(
        TaskSubject::Topic(meep_topic::TopicId(view)).marker(),
        format!("[meep topic:{view}]")
    );
    Ok(())
}

#[tokio::test]
async fn resuming_a_live_view_run_explains_the_conflict_without_cancelling_it() -> Result<()> {
    let server = Server::http("127.0.0.1:0").map_err(anyhow::Error::from_boxed)?;
    let origin = format!("http://{}", server.server_addr());
    let task = Uuid::new_v4();
    let run = Uuid::new_v4();
    let mock = std::thread::spawn(move || -> Result<()> {
        let request = server
            .recv_timeout(Duration::from_secs(30))?
            .context("models")?;
        assert_eq!(request.url(), "/api/projects/7/tasks/models/");
        request.respond(Response::from_string(json!({"models":[{"model":"claude-test","display_name":"Claude","runtime_adapter":"claude"}]}).to_string()))?;
        let mut request = server
            .recv_timeout(Duration::from_secs(30))?
            .context("resume")?;
        assert_eq!(request.url(), format!("/api/projects/7/tasks/{task}/run/"));
        let body: Value = serde_json::from_reader(request.as_reader())?;
        assert_eq!(body["resume_from_run_id"], json!(run));
        // The person's model and effort reach the authoring run.
        assert_eq!(body["model"], "claude-test");
        assert_eq!(body["reasoning_effort"], "high");
        request.respond(Response::from_string(json!({"error":"This task already has a run in progress. Wait for it to finish or cancel it first."}).to_string()).with_status_code(409))?;
        assert!(server.recv_timeout(Duration::from_millis(200))?.is_none());
        Ok(())
    });
    let agent = PostHogAgent::new(&origin, 7, "fixture")?;
    let error = agent
        .author_view(
            Uuid::new_v4(),
            Some(&RunHandle(json!([task, run]))),
            "Update",
            "https://example.test/mcp",
            "new-bearer",
            Some("claude-test"),
            Some("high"),
            vec![],
        )
        .await
        .unwrap_err();
    assert!(
        error.to_string().contains("Start a new session"),
        "{error:#}"
    );
    mock.join().expect("fixture server")?;
    Ok(())
}

#[test]
fn topic_brief_selects_evidence_and_bounds_only_the_tool_enabled_snapshot() -> Result<()> {
    let now = "2026-06-01T00:00:00Z";
    let thread = Uuid::new_v4();
    let fact = |text: &str| json!({"id":Uuid::new_v4(),"text":text,"provenance":{"author":"tester","via":"fixture","at":now}});
    let mut linked = fact("linked by provenance");
    linked["provenance"]["thread"] = json!(thread);
    let dependency = fact("action dependency");
    let cited = fact("cited in oldest message");
    let unrelated = fact("uncited assertion");
    let mut disputed = fact("withdrawn, under review");
    disputed["withdrawn_at"] = json!(now);
    let watch = json!({"id":Uuid::new_v4(),"connection":"fixture","kind":"feed","key":"source","label":"watch label"});
    let mut messages: Vec<_> = (0..52).map(|i| json!({"id":Uuid::new_v4(),"producer":"System","author":"tester","at":now,"text":format!("message {i}")})).collect();
    messages[0]["text"] = json!(format!("oldest cites {}", cited["id"].as_str().unwrap()));
    let mut run: AgentRun = serde_json::from_value(json!({
        "topic_name":"Test","mission":"Track evidence","rules":[],"started_at":now,
        "facts":[linked,dependency,cited,unrelated],"disputed_fact_ids":[disputed["id"]],
        "watches":[watch],"routines":[{"id":"sort","name":"Sort inbox","trigger":"event","backend":"system","external_id":"sort","health":"Ok","watches":[watch]}],
        "task":{"id":Uuid::new_v4(),"title":"source title","queued":false,"added_by":{"Inbox":thread},"from_thread":thread,"column":"Todo","created_at":now,"updated_at":now,
                "log":[{"at":now,"text":"inbound evidence"}],"action":{"kind":"publish","label":"Post","done_label":"Posted","depends_on_facts":[dependency["id"]],"payload":{}}},
        "thread":{"id":thread,"subject":"source subject","summary":"source summary","state":"Handled","messages":messages,"outcomes":[],"key":"fixture","unseen":false,"created_at":now,"updated_at":now}
    }))?;
    run.historical_facts.push(serde_json::from_value(disputed)?);

    let brief = brief::run_context(&run, true)?;
    let source = &brief["untrusted_source_data"];
    let texts: Vec<_> = source["facts"]
        .as_array()
        .unwrap()
        .iter()
        .map(|f| f["text"].as_str().unwrap())
        .collect();
    assert_eq!(
        texts,
        [
            "linked by provenance",
            "action dependency",
            "cited in oldest message",
            "withdrawn, under review"
        ]
    );
    assert_eq!(brief["more"]["facts"], 1);
    assert_eq!(brief["more"]["watches"], 1);
    assert!(
        brief["more"]["how"]
            .as_str()
            .unwrap()
            .contains("list_facts")
    );
    assert_eq!(
        brief["routines"],
        json!([{"id":"sort","name":"Sort inbox"}])
    );
    assert_eq!(source["thread"]["omitted_messages"], 2);
    let messages = source["thread"]["messages"].as_array().unwrap();
    assert_eq!(messages.len(), 50);
    assert_eq!(messages.first().unwrap()["text"], "message 2");
    assert_eq!(messages.last().unwrap()["text"], "message 51");
    assert_eq!(
        brief["task"]["untrusted_source_data"]["title"],
        "source title"
    );
    assert_eq!(
        brief["task"]["untrusted_source_data"]["log"][0]["text"],
        "inbound evidence"
    );
    for excluded in ["uncited assertion", "watch label", "oldest cites"] {
        assert!(!brief.to_string().contains(excluded));
    }
    let full = brief::run_context(&run, false)?;
    assert_eq!(full, serde_json::to_value(&run)?);
    assert_eq!(full["facts"].as_array().unwrap().len(), 4);
    assert_eq!(full["facts"][3]["id"], unrelated["id"]);
    assert_eq!(full["watches"][0], watch);
    assert_eq!(full["thread"]["messages"].as_array().unwrap().len(), 52);
    Ok(())
}

#[test]
fn routine_decision_task_brief_keeps_the_full_observation() -> Result<()> {
    use meep_topic::{Decision, Message, Producer, Source, Suggestion, Topic, TopicState};
    let now = DateTime::UNIX_EPOCH;
    let topic = Uuid::new_v4().into();
    let thread = Uuid::new_v4().into();
    let message = Uuid::new_v4().into();
    let task = Uuid::new_v4().into();
    let body = "How should we handle this item?\n\nThe fixture flag is inactive.\n\nRollout details remain available.";
    let mut state = TopicState::new(Topic::new(topic, "Fixture", now));
    state.receive(
        Message {
            id: message,
            producer: Producer::Routine("sort".into()),
            origin: Some(Source::Topic(topic).into_origin("Sort".into(), now, None)),
            author: "Sort".into(),
            at: now,
            text: body.into(),
            external_id: None,
        },
        "source",
        thread,
        now,
    )?;
    let suggestion = Suggestion::MakeTask { title: body.into() };
    state.decide_message(
        thread,
        message,
        Decision::Ask {
            summary: body.into(),
            reason: body.into(),
            suggestions: vec![suggestion.clone()],
        },
        now,
    )?;
    state.answer(thread, suggestion, task, now)?;
    let run: AgentRun = serde_json::from_value(json!({
        "topic_name":"Fixture", "mission":"", "rules":[], "started_at":now,
        "facts":[], "disputed_fact_ids":[], "watches":[], "routines":[],
        "task":state.tasks[0], "thread":state.threads[0]
    }))?;
    for tools in [false, true] {
        let brief = brief::run_context(&run, tools)?;
        let source_thread = if tools {
            &brief["untrusted_source_data"]["thread"]
        } else {
            &brief["thread"]
        };
        assert_eq!(source_thread["messages"][0]["text"], body);
        assert_eq!(
            run.task.title,
            "The fixture flag is inactive.\n\nRollout details remain available."
        );
        assert_eq!(
            meep_topic::title_line(&run.task.title),
            "The fixture flag is inactive."
        );
    }
    Ok(())
}

#[tokio::test]
async fn starts_on_the_posthog_default_and_leaves_an_unset_default_unpinned() -> Result<()> {
    let server = Server::http("127.0.0.1:0").map_err(anyhow::Error::from_boxed)?;
    let origin = format!("http://{}", server.server_addr());
    let task_id = Uuid::new_v4();
    let mock = std::thread::spawn(move || -> Result<()> {
        for (config, runtime, model, adapter, effort, tools) in [
            (
                json!({"runtime":"acp","runtime_adapter":"codex","model":"gpt-5","reasoning_effort":"high"}),
                None,
                Some("gpt-5"),
                Some("codex"),
                Some("high"),
                false,
            ),
            (
                json!({"runtime":"pi","runtime_adapter":null,"model":"pi-model","reasoning_effort":"low"}),
                Some("pi"),
                Some("pi-model"),
                None,
                Some("low"),
                false,
            ),
            (
                json!({"runtime":"acp","runtime_adapter":null,"model":null,"reasoning_effort":null}),
                None,
                None,
                None,
                None,
                true,
            ),
        ] {
            let req = server
                .recv_timeout(Duration::from_secs(10))?
                .context("config")?;
            assert_eq!(req.url(), "/api/projects/7/tasks/@me/config/");
            req.respond(Response::from_string(
                json!({"resolved_ai_run_defaults":config}).to_string(),
            ))?;
            let mut req = server
                .recv_timeout(Duration::from_secs(10))?
                .context("create")?;
            let body: Value = serde_json::from_reader(req.as_reader())?;
            assert_eq!(body.get("runtime").and_then(Value::as_str), runtime);
            req.respond(Response::from_string(json!({"id":task_id}).to_string()))?;
            let mut req = server
                .recv_timeout(Duration::from_secs(10))?
                .context("start")?;
            let body: Value = serde_json::from_reader(req.as_reader())?;
            assert_eq!(body.get("model").and_then(Value::as_str), model);
            assert_eq!(body.get("runtime_adapter").and_then(Value::as_str), adapter);
            assert_eq!(body.get("reasoning_effort").and_then(Value::as_str), effort);
            assert_eq!(body.get("imported_mcp_servers").is_some(), tools);
            req.respond(Response::from_string(
                json!({"run":{"id":Uuid::new_v4(),"status":"queued"}}).to_string(),
            ))?;
        }
        Ok(())
    });
    let engine = Engine::with_clock(
        Arc::new(crate::MemoryStore::default()),
        Limits {
            max_hops: 2,
            max_runs_per_hour: 4,
        },
        Arc::new(crate::FixtureAgent::default()),
        Arc::new(FixtureSorter),
        Arc::new(ManualClock::new(DateTime::UNIX_EPOCH)),
    )
    .await?;
    let (topic, _) = engine.create_topic("Fixture", "Test").await?;
    engine.add_task(topic, "Test task").await?;
    let task = engine.topic(topic)?.tasks[0].clone();
    let context = AgentRun {
        topic_name: "Fixture".into(),
        goals: vec![],
        context_sources: vec![],
        watches: vec![],
        routines: vec![],
        mission: "Test".into(),
        facts: vec![],
        historical_facts: vec![],
        disputed_fact_ids: Default::default(),
        rules: vec![],
        task,
        thread: None,
        setup: false,
        started_at: DateTime::UNIX_EPOCH,
    };
    let agent = PostHogAgent::new(&origin, 7, "fixture")?;
    for _ in 0..3 {
        agent
            .start_with_mcp(
                topic,
                context.clone(),
                Some(("https://example.test/mcp", "fixture")),
            )
            .await?;
    }
    mock.join().expect("fixture server")?;
    Ok(())
}

#[test]
fn a_restated_answer_is_shown_once() {
    let blocks = [
        ("text", "Let me check."),
        ("tool", "execute-sql"),
        (
            "text",
            "I'm working in \"Default project\" (id 1), with [0 uploads](http://x).",
        ),
        (
            "text",
            "I'm working in \"Default project\" (id 1), with 0 uploads.",
        ),
    ];
    assert_eq!(
        super::final_text(&blocks, "whole"),
        "I'm working in \"Default project\" (id 1), with 0 uploads."
    );
}
