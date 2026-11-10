mod common;

use std::sync::Arc;

use common::{shared, test_message, MockOutputs};
use ingestion_framework::warning_handling::OutputsWarningEmitter;
use ingestion_framework::{
    create_ok_context, dlq, new_chunk_pipeline, new_pipeline, ok, step, HasMessage, HasTeamId,
    KafkaMessage, OkResultWithContext, PipelineBuilder, PipelineConfig, ProcessingStep,
    PromiseScheduler, SideEffect, SideEffectHandlingConfig, StartPipelineBuilder,
};

#[tokio::test]
async fn steps_are_created_via_factory_functions() {
    fn create_process_step() -> ProcessingStep<String, (String, bool)> {
        step("processStep", |v: String| async move {
            Ok(ok((v.to_uppercase(), true)))
        })
    }
    let pipeline = new_pipeline::<String, ()>()
        .pipe(create_process_step())
        .build();
    let r = pipeline
        .process(create_ok_context("hello".into(), ()))
        .await
        .unwrap();
    assert_eq!(r.value(), Some(&("HELLO".to_string(), true)));
}

#[tokio::test]
async fn pipelines_are_created_via_factory_functions_to_ensure_single_caller() {
    fn create_my_pipeline() -> ingestion_framework::DynPipeline<i64, (i64, bool), ()> {
        new_pipeline::<i64, ()>()
            .pipe(step(
                "processStep",
                |id: i64| async move { Ok(ok((id, true))) },
            ))
            .build()
    }
    let p1 = create_my_pipeline();
    let p2 = create_my_pipeline();
    assert!(!Arc::ptr_eq(&p1, &p2));
    assert_eq!(
        p1.process(create_ok_context(1, ()))
            .await
            .unwrap()
            .value()
            .unwrap()
            .0,
        1
    );
    assert_eq!(
        p2.process(create_ok_context(2, ()))
            .await
            .unwrap()
            .value()
            .unwrap()
            .0,
        2
    );
}

#[tokio::test]
async fn factory_functions_accept_configuration_parameters() {
    fn create_multiply_step(multiplier: i64) -> ProcessingStep<i64, (i64, i64)> {
        step("multiplyStep", move |v: i64| async move {
            Ok(ok((v, v * multiplier)))
        })
    }
    let pipeline = new_pipeline::<i64, ()>()
        .pipe(create_multiply_step(3))
        .build();
    let r = pipeline.process(create_ok_context(10, ())).await.unwrap();
    assert_eq!(r.value().unwrap().1, 30);
}

#[tokio::test]
async fn factory_functions_can_inject_multiple_dependencies() {
    struct UserService;
    impl UserService {
        async fn get_user(&self, id: &str) -> String {
            format!("User {id}")
        }
    }
    struct AuditService;
    impl AuditService {
        async fn log(&self, _msg: String) {}
    }
    fn create_enrich_step(
        users: Arc<UserService>,
        audit: Arc<AuditService>,
    ) -> ProcessingStep<String, (String, String, bool)> {
        step("enrichStep", move |user_id: String| {
            let (users, audit) = (users.clone(), audit.clone());
            async move {
                let name = users.get_user(&user_id).await;
                let message = format!("Enriched user {user_id}");
                let effect = SideEffect::spawn(async move {
                    audit.log(message).await;
                    Ok(())
                });
                Ok(ok((user_id, name, true)).with_side_effect(effect))
            }
        })
    }
    let pipeline = new_pipeline::<String, ()>()
        .pipe(create_enrich_step(
            Arc::new(UserService),
            Arc::new(AuditService),
        ))
        .build();
    let r = pipeline
        .process(create_ok_context("123".into(), ()))
        .await
        .unwrap();
    assert_eq!(r.value().unwrap().1, "User 123");
}

#[tokio::test]
async fn steps_extend_input_types_with_new_properties() {
    // Node extends with intersection types (`T & ValidateOutput`). Rust wraps the input.
    struct Validated<T> {
        inner: T,
        is_valid: bool,
    }
    struct Enriched<T> {
        inner: T,
        enriched_at: i64,
    }
    let pipeline = new_pipeline::<String, ()>()
        .pipe(step("validateStep", |raw: String| async move {
            let is_valid = !raw.is_empty();
            Ok(ok(Validated {
                inner: raw,
                is_valid,
            }))
        }))
        .pipe(step("enrichStep", |v: Validated<String>| async move {
            Ok(ok(Enriched {
                inner: v,
                enriched_at: chrono::Utc::now().timestamp_millis(),
            }))
        }))
        .build();
    let r = pipeline
        .process(create_ok_context("test data".into(), ()))
        .await
        .unwrap();
    let v = r.value().unwrap();
    assert_eq!(v.inner.inner, "test data");
    assert!(v.inner.is_valid);
    assert!(v.enriched_at > 0);
}

#[tokio::test]
async fn terminal_transforms_produce_different_output_shapes() {
    let pipeline = new_pipeline::<(&'static str, bool, i64), ()>()
        .pipe(step(
            "summarizeStep",
            |e: (&'static str, bool, i64)| async move {
                Ok(ok(format!("Event {}: valid={} at {}", e.0, e.1, e.2)))
            },
        ))
        .build();
    let r = pipeline
        .process(create_ok_context(("evt-1", true, 1000), ()))
        .await
        .unwrap();
    assert_eq!(r.value().unwrap(), "Event evt-1: valid=true at 1000");
}

#[tokio::test]
async fn terminal_steps_return_void_with_side_effects() {
    let emitted = shared(Vec::<&'static str>::new());
    let e = emitted.clone();
    let pipeline = new_pipeline::<&'static str, ()>()
        .pipe(step("emitStep", move |id: &'static str| {
            let e = e.clone();
            async move {
                Ok(ok(()).with_side_effect(SideEffect::spawn(async move {
                    e.lock().unwrap().push(id);
                    Ok(())
                })))
            }
        }))
        .build();
    let mut r = pipeline
        .process(create_ok_context("evt-1", ()))
        .await
        .unwrap();
    assert_eq!(r.value(), Some(&()));
    for s in std::mem::take(&mut r.context.side_effects) {
        s.wait().await.unwrap();
    }
    assert!(emitted.lock().unwrap().contains(&"evt-1"));
}

#[tokio::test]
async fn simple_terminal_steps_return_ok_unit() {
    let pipeline = new_pipeline::<bool, ()>()
        .pipe(step("skipStep", |_skip: bool| async move { Ok(ok(())) }))
        .build();
    assert!(pipeline
        .process(create_ok_context(true, ()))
        .await
        .unwrap()
        .is_ok());
}

#[derive(Debug, Clone)]
struct MsgCtx {
    message: KafkaMessage,
}
#[derive(Debug, Clone)]
struct TeamMsgCtx {
    message: KafkaMessage,
    team_id: Option<i64>,
}
impl From<MsgCtx> for TeamMsgCtx {
    fn from(c: MsgCtx) -> Self {
        Self {
            message: c.message,
            team_id: None,
        }
    }
}
impl HasMessage for MsgCtx {
    fn message(&self) -> &KafkaMessage {
        &self.message
    }
}
impl HasMessage for TeamMsgCtx {
    fn message(&self) -> &KafkaMessage {
        &self.message
    }
}
impl HasTeamId for TeamMsgCtx {
    fn team_id(&self) -> i64 {
        self.team_id.unwrap_or_default()
    }
}

#[derive(Debug, Clone)]
struct PreTeam {
    team_id: i64,
    event_name: String,
}

#[tokio::test]
async fn pipelines_are_organized_into_preprocessing_and_processing_phases() {
    let phase_log = shared(Vec::<&'static str>::new());
    let scheduler = PromiseScheduler::new();

    let (l1, l2, l3) = (phase_log.clone(), phase_log.clone(), phase_log.clone());
    let pre_team = move |b: StartPipelineBuilder<KafkaMessage, MsgCtx>| -> PipelineBuilder<KafkaMessage, PreTeam, MsgCtx> {
        b.pipe(step("parseStep", move |m: KafkaMessage| {
            l1.lock().unwrap().push("pre-team: parse");
            async move {
                match serde_json::from_slice::<serde_json::Value>(m.value.as_deref().unwrap_or(b"{}")) {
                    Ok(v) => Ok(ok(PreTeam {
                        team_id: v["teamId"].as_i64().unwrap_or_default(),
                        event_name: v["eventName"].as_str().unwrap_or_default().to_string(),
                    })),
                    Err(e) => Ok(dlq("Failed to parse message", Some(e.into()))),
                }
            }
        }))
    };
    let post_team = move |b: StartPipelineBuilder<PreTeam, TeamMsgCtx>| {
        b.pipe(step("validateStep", move |p: PreTeam| {
            l2.lock().unwrap().push("post-team: validate");
            async move { Ok(ok((p, true))) }
        }))
    };
    let processing = move |b: StartPipelineBuilder<(PreTeam, bool), TeamMsgCtx>| {
        b.pipe(step(
            "processStep",
            move |(p, _validated): (PreTeam, bool)| {
                l3.lock().unwrap().push("processing: process");
                async move { Ok(ok(format!("{} for Team {}", p.event_name, p.team_id))) }
            },
        ))
    };

    let pipeline =
        new_chunk_pipeline::<KafkaMessage, MsgCtx>()
            .message_aware(move |b| {
                b.concurrently(pre_team, None).filter_map(
                    |el: OkResultWithContext<PreTeam, MsgCtx>| {
                        let team_id = el.value.team_id;
                        OkResultWithContext {
                            value: el.value,
                            context: el.context.map_data(|c| TeamMsgCtx {
                                message: c.message,
                                team_id: Some(team_id),
                            }),
                        }
                    },
                    move |b| {
                        b.team_aware(move |b| {
                            b.concurrently(post_team, None).concurrently_per_group(
                                |item: &(PreTeam, bool)| item.0.team_id,
                                move |g| g.sequentially(processing),
                                None,
                            )
                        })
                        .handle_ingestion_warnings(Arc::new(OutputsWarningEmitter {
                            outputs: Arc::new(MockOutputs::default()),
                        }))
                    },
                )
            })
            .handle_results(PipelineConfig {
                outputs: Arc::new(MockOutputs::default()),
                scheduler: Arc::new(scheduler.clone()),
                reject_on_dlq_failure: false,
            })
            .handle_side_effects(
                Arc::new(scheduler),
                SideEffectHandlingConfig {
                    await_side_effects: true,
                },
            )
            .build();

    let mut message = test_message(None);
    message.value = Some(br#"{"teamId":42,"eventName":"pageview"}"#.to_vec().into());
    pipeline.feed(vec![create_ok_context(message.clone(), MsgCtx { message })]);
    let results = pipeline.next().await.unwrap().unwrap();
    assert_eq!(
        *phase_log.lock().unwrap(),
        vec![
            "pre-team: parse",
            "post-team: validate",
            "processing: process"
        ]
    );
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].value().unwrap(), "pageview for Team 42");
}
