//! Mirrors `docs/10-branching.test.ts`. Node checks branch coverage at compile time; branch
//! names are strings here, so only the run-time DLQ path exists.

mod common;

use common::shared;
use ingestion_framework::{create_ok_context, new_pipeline, ok, step, PipelineResultType};

type Event = (&'static str, &'static str);

#[tokio::test]
async fn branching_routes_items_to_different_sub_pipelines() {
    let calls = shared(Vec::<&'static str>::new());
    let (c1, c2, c3) = (calls.clone(), calls.clone(), calls.clone());
    let pipeline = new_pipeline::<Event, ()>()
        .branching(
            |e: &Event| e.0.to_string(),
            move |b| {
                b.branch("pageview", move |s| {
                    s.pipe(step("pageviewStep", move |e: Event| {
                        c1.lock().unwrap().push("pageview");
                        async move { Ok(ok(format!("PAGE: {}", e.1))) }
                    }))
                })
                .branch("click", move |s| {
                    s.pipe(step("clickStep", move |e: Event| {
                        c2.lock().unwrap().push("click");
                        async move { Ok(ok(format!("CLICK: {}", e.1))) }
                    }))
                })
                .branch("custom", move |s| {
                    s.pipe(step("customStep", move |e: Event| {
                        c3.lock().unwrap().push("custom");
                        async move { Ok(ok(e.1.to_string())) }
                    }))
                })
            },
        )
        .build();
    let page = pipeline
        .process(create_ok_context(("pageview", "home"), ()))
        .await
        .unwrap();
    let click = pipeline
        .process(create_ok_context(("click", "button"), ()))
        .await
        .unwrap();
    assert_eq!(page.value().unwrap(), "PAGE: home");
    assert_eq!(click.value().unwrap(), "CLICK: button");
    assert_eq!(*calls.lock().unwrap(), vec!["pageview", "click"]);
}

#[tokio::test]
async fn unknown_branch_routes_to_dlq() {
    let pipeline = new_pipeline::<Event, ()>()
        .branching(
            |e: &Event| e.0.to_string(),
            |b| {
                b.branch("pageview", |s| {
                    s.pipe(step("pageviewStep", |e: Event| async move { Ok(ok(e)) }))
                })
            },
        )
        .build();
    let r = pipeline
        .process(create_ok_context(("unknown", "test"), ()))
        .await
        .unwrap();
    assert_eq!(r.result.result_type(), PipelineResultType::Dlq);
    assert_eq!(r.result.reason(), Some("Unknown branch: unknown"));
}

#[tokio::test]
async fn branches_must_converge_to_the_same_output_type() {
    #[derive(Debug, PartialEq)]
    enum Output {
        Number(i64),
        Str(String),
    }
    let pipeline = new_pipeline::<(&'static str, &'static str), ()>()
        .branching(
            |i: &(&'static str, &'static str)| i.0.to_string(),
            |b| {
                b.branch("toNumber", |s| {
                    s.pipe(step(
                        "toNumberStep",
                        |i: (&'static str, &'static str)| async move {
                            Ok(ok(Output::Number(i.1.parse().unwrap())))
                        },
                    ))
                })
                .branch("toString", |s| {
                    s.pipe(step(
                        "toStringStep",
                        |i: (&'static str, &'static str)| async move {
                            Ok(ok(Output::Str(i.1.to_uppercase())))
                        },
                    ))
                })
            },
        )
        .build();
    let n = pipeline
        .process(create_ok_context(("toNumber", "42"), ()))
        .await
        .unwrap();
    let s = pipeline
        .process(create_ok_context(("toString", "hello"), ()))
        .await
        .unwrap();
    assert_eq!(n.value(), Some(&Output::Number(42)));
    assert_eq!(s.value(), Some(&Output::Str("HELLO".into())));
}
