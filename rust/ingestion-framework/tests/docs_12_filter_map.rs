//! Mirrors `docs/12-filter-map.test.ts`. Node types the output context as a union; here the
//! team-aware context converts from the message context, with `team_id` unset for passthroughs.

mod common;

use std::sync::Arc;

use common::{shared, test_message, MockOutputs};
use ingestion_framework::warning_handling::OutputsWarningEmitter;
use ingestion_framework::{
    chunk_step, create_ok_context, dlq, new_chunk_pipeline, ok, redirect, HasMessage, HasTeamId,
    KafkaMessage, OkResultWithContext, PipelineConfig, PipelineWarning, PromiseScheduler,
    SideEffectHandlingConfig, DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT,
};
use serde_json::json;

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
impl HasMessage for TeamMsgCtx {
    fn message(&self) -> &KafkaMessage {
        &self.message
    }
}
impl HasTeamId for TeamMsgCtx {
    fn team_id(&self) -> i64 {
        self.team_id
            .expect("team set inside the filter_map sub-pipeline")
    }
}

#[derive(Debug, Clone)]
struct RawEvent {
    team_id: i64,
    name: &'static str,
}

#[tokio::test]
async fn filter_map_enables_team_aware_processing_with_non_ok_passthrough() {
    let processed = shared(Vec::<(&'static str, i64)>::new());
    let p = processed.clone();
    let outputs = MockOutputs::default();
    let warning_outputs = MockOutputs::default();
    let scheduler = PromiseScheduler::new();
    let wo = warning_outputs.clone();

    let pipeline = new_chunk_pipeline::<RawEvent, MsgCtx>()
        .pipe_chunk(chunk_step(
            "teamLookupStep",
            |events: Vec<RawEvent>| async move {
                Ok(events
                    .into_iter()
                    .map(|e| {
                        if e.team_id == 999 {
                            dlq("Team not found", Some(anyhow::anyhow!("Unknown team")))
                        } else {
                            ok((e.clone(), e.team_id))
                        }
                    })
                    .collect())
            },
        ))
        .gather()
        .filter_map(
            |el: OkResultWithContext<(RawEvent, i64), MsgCtx>| {
                let team_id = el.value.1;
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
                    b.pipe_chunk(chunk_step(
                        "processEventStep",
                        move |events: Vec<(RawEvent, i64)>| {
                            let p = p.clone();
                            async move {
                                Ok(events
                                    .into_iter()
                                    .map(|item| {
                                        if item.0.name == "overflow" {
                                            return redirect("Event overflow", "overflow");
                                        }
                                        let mut r = ok(item.clone());
                                        if item.0.name == "deprecated_event" {
                                            r = r.with_warning(PipelineWarning::new(
                                                "event_dropped_by_transformation",
                                                json!({"eventName": item.0.name}),
                                            ));
                                        }
                                        p.lock().unwrap().push((item.0.name, item.1));
                                        r
                                    })
                                    .collect())
                            }
                        },
                    ))
                    .gather()
                })
                .handle_ingestion_warnings(Arc::new(OutputsWarningEmitter {
                    outputs: Arc::new(wo),
                }))
            },
        )
        .message_aware(|b| b)
        .handle_results(PipelineConfig {
            outputs: Arc::new(outputs.clone()),
            scheduler: Arc::new(scheduler.clone()),
            reject_on_dlq_failure: false,
        })
        .handle_side_effects(
            Arc::new(scheduler.clone()),
            SideEffectHandlingConfig {
                await_side_effects: true,
            },
        )
        .build();

    let feed = |team_id, name| {
        create_ok_context(
            RawEvent { team_id, name },
            MsgCtx {
                message: test_message(None),
            },
        )
    };
    pipeline.feed(vec![
        feed(1, "pageview"),
        feed(999, "will_fail"),
        feed(2, "overflow"),
        feed(3, "deprecated_event"),
    ]);

    let mut all = Vec::new();
    while let Some(chunk) = pipeline.next().await.unwrap() {
        all.extend(chunk);
    }
    assert_eq!(all.len(), 4);
    assert_eq!(all.iter().filter(|r| r.is_ok()).count(), 2);
    assert_eq!(
        *processed.lock().unwrap(),
        vec![("pageview", 1), ("deprecated_event", 3)]
    );
    let produced: Vec<String> = outputs.calls().into_iter().map(|c| c.0).collect();
    assert!(produced.contains(&DLQ_OUTPUT.to_string()));
    assert!(produced.contains(&"overflow".to_string()));
    let warnings = warning_outputs.calls();
    assert_eq!(warnings.len(), 1);
    assert_eq!(warnings[0].0, INGESTION_WARNINGS_OUTPUT);
    let value = String::from_utf8(warnings[0].1.value.clone().unwrap().to_vec()).unwrap();
    assert!(
        value.contains("\"type\":\"event_dropped_by_transformation\""),
        "{value}"
    );
}
