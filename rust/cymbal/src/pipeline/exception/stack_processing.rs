use std::{collections::HashMap, sync::Arc};

use common_types::error_tracking::RawFrameId;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::{PipelineResult, UnhandledError},
    fingerprinting::resolve_fingerprint,
    frames::RawFrame,
    langs::java::RawJavaFrame,
    metric_consts::{
        FINGERPRINT_BATCH_TIME, FRAME_BATCH_TIME, FRAME_RESOLUTION, JAVA_EXCEPTION_REMAP_FAILED,
    },
    symbol_store::{chunk_id::OrChunkId, dart_minified_names::lookup_minified_type, Catalog},
    types::{FingerprintedErrProps, RawErrProps, Stacktrace},
};

pub async fn do_stack_processing(
    context: Arc<AppContext>,
    events: &[PipelineResult],
    mut indexed_props: Vec<(usize, RawErrProps)>,
) -> Result<Vec<(usize, FingerprintedErrProps)>, (usize, Arc<UnhandledError>)> {
    let frame_batch_timer = common_metrics::timing_guard(FRAME_BATCH_TIME, &[]);
    let mut frame_resolve_handles = HashMap::new();
    for (index, props) in indexed_props.iter_mut() {
        let team_id = events[*index]
            .as_ref()
            .expect("no events have been dropped since indexed-property gathering")
            .team_id;

        for exception in props.exception_list.iter_mut() {
            exception.exception_id = Some(Uuid::now_v7().to_string());

            let frames = match exception.stack.take() {
                Some(Stacktrace::Raw { frames }) => {
                    if frames.is_empty() {
                        continue;
                    }
                    frames
                }
                Some(Stacktrace::Resolved { frames }) => {
                    // This stack trace is already resolved, we have no work to do.
                    exception.stack = Some(Stacktrace::Resolved { frames });
                    continue;
                }
                None => {
                    continue; // It was None before and it's none after the take
                }
            };

            for frame in frames.iter() {
                let id = frame.raw_id(team_id);
                if frame_resolve_handles.contains_key(&id) {
                    // We've already spawned a task to resolve this frame, so we don't need to do it again.
                    continue;
                }

                // We need a cloned frame to move into the closure below
                let frame = frame.clone();
                let context = context.clone();
                // Spawn a concurrent task for resolving every frame
                let handle = tokio::spawn(async move {
                    context.worker_liveness.report_healthy().await;
                    metrics::counter!(FRAME_RESOLUTION).increment(1);
                    let res = context
                        .resolver
                        .resolve(&frame, team_id, &context.posthog_pool, &context.catalog)
                        .await;
                    context.worker_liveness.report_healthy().await;
                    res
                });
                frame_resolve_handles.insert(id, handle);
            }

            if let Some(RawFrame::Java(frame)) = frames.first() {
                if let Some(module) = &exception.module {
                    if let Some((remapped_module, remapped_type)) = remap_exception_type_and_module(
                        module,
                        &exception.exception_type,
                        team_id,
                        frame,
                        &context.catalog,
                    )
                    .await
                    {
                        exception.module = Some(remapped_module);
                        exception.exception_type = remapped_type;
                    }
                }
            }

            // Handle dart2js minified exception types (e.g., "minified:BA" -> "UnsupportedError")
            // Flutter Web uses posthog-js, so frames come as JavaScriptWeb with chunk_id
            if exception.exception_type.starts_with("minified:") {
                if let Some(remapped_type) = remap_dart_minified_exception_type(
                    &exception.exception_type,
                    &frames,
                    team_id,
                    &context.catalog,
                )
                .await
                {
                    exception.exception_type = remapped_type;
                }
            }

            // Put the frames back on the exception, now that we're done mutating them until we've
            // gathered our lookup table.
            exception.stack = Some(Stacktrace::Raw { frames });
        }
    }

    let mut frame_lookup_table = HashMap::new();
    for (id, handle) in frame_resolve_handles.into_iter() {
        let res = match handle.await.expect("Frame resolve task didn't panic") {
            Ok(r) => r,
            Err(e) => {
                let index = find_index_with_matching_frame_id(&id, &indexed_props);
                return Err((index, e));
            }
        };
        frame_lookup_table.insert(id, res);
    }
    frame_batch_timer.fin();

    let fingerprint_timer = common_metrics::timing_guard(FINGERPRINT_BATCH_TIME, &[]);
    let mut indexed_fingerprinted = Vec::new();
    for (index, mut props) in indexed_props.into_iter() {
        let team_id = events[index]
            .as_ref()
            .expect("no events have been dropped since indexed-property gathering")
            .team_id;

        for exception in props.exception_list.iter_mut() {
            exception.stack = exception
                .stack
                .take()
                .map(|s| {
                    s.resolve(team_id, &frame_lookup_table)
                        .ok_or(UnhandledError::Other(
                            "Stacktrace::resolve returned None".to_string(),
                        ))
                })
                .transpose()
                .map_err(|e| (index, Arc::new(e)))?;
        }

        let team_id = events[index]
            .as_ref()
            .expect("no events have been dropped since indexed-property gathering")
            .team_id;

        let mut conn = context
            .posthog_pool
            .acquire()
            .await
            .map_err(|e| (index, Arc::new(e.into())))?;

        let proposed = resolve_fingerprint(&mut conn, &context.team_manager, team_id, &props)
            .await
            .map_err(|e| (index, Arc::new(e)))?;

        let fingerprinted = props.to_fingerprinted(proposed);
        indexed_fingerprinted.push((index, fingerprinted));
    }
    fingerprint_timer.fin(); // Could just let this be dropped, tbh

    Ok(indexed_fingerprinted)
}

fn find_index_with_matching_frame_id(id: &RawFrameId, list: &[(usize, RawErrProps)]) -> usize {
    for (index, props) in list.iter() {
        for exception in props.exception_list.iter() {
            if let Some(Stacktrace::Raw { frames }) = &exception.stack {
                for frame in frames {
                    if frame.raw_id(id.team_id) == *id {
                        return *index;
                    }
                }
            }
        }
    }
    0
}

async fn remap_exception_type_and_module(
    module: &str,
    exception_type: &str,
    team_id: i32,
    frame: &RawJavaFrame,
    catalog: &Catalog,
) -> Option<(String, String)> {
    let class = format!("{module}.{exception_type}");

    match frame.remap_class(team_id, &class, catalog).await {
        Ok(Some(s)) => match split_last_dot(&s) {
            Ok((remapped_module, remapped_type)) => {
                Some((remapped_module.to_string(), remapped_type.to_string()))
            }
            Err(_) => {
                metrics::counter!(JAVA_EXCEPTION_REMAP_FAILED, "reason" => "invalid_format")
                    .increment(1);
                None
            }
        },
        Ok(None) => {
            metrics::counter!(JAVA_EXCEPTION_REMAP_FAILED, "reason" => "class_not_found")
                .increment(1);
            None
        }
        Err(_) => {
            metrics::counter!(JAVA_EXCEPTION_REMAP_FAILED, "reason" => "lookup_error").increment(1);
            None
        }
    }
}

fn split_last_dot(s: &str) -> Result<(&str, &str), UnhandledError> {
    let mut parts = s.rsplitn(2, '.');
    let last = parts.next().unwrap();
    let before = parts.next().ok_or(UnhandledError::Other(
        "Could not split remapped module and type".to_string(),
    ))?;
    Ok((before, last))
}

/// Remaps dart2js minified exception types (e.g., "minified:BA" -> "UnsupportedError")
/// by looking up the minified name in the sourcemap's x_org_dartlang_dart2js extension.
async fn remap_dart_minified_exception_type(
    exception_type: &str,
    frames: &[RawFrame],
    team_id: i32,
    catalog: &Catalog,
) -> Option<String> {
    let chunk_id = frames.iter().find_map(|frame| match frame {
        RawFrame::JavaScriptWeb(js_frame) => js_frame.chunk_id.clone(),
        RawFrame::JavaScriptNode(node_frame) => node_frame.chunk_id.clone(),
        RawFrame::LegacyJS(js_frame) => js_frame.chunk_id.clone(),
        _ => None,
    })?;

    let sourcemap = catalog
        .smp
        .lookup(team_id, OrChunkId::ChunkId(chunk_id))
        .await
        .ok()?;

    let minified_names = sourcemap.get_dart_minified_names()?;

    lookup_minified_type(minified_names, exception_type)
}

#[cfg(test)]
mod test {
    use std::sync::Arc;

    use chrono::Utc;
    use mockall::predicate;
    use posthog_symbol_data::write_symbol_data;
    use sqlx::PgPool;
    use uuid::Uuid;

    use crate::{
        config::Config,
        langs::{java::RawJavaFrame, CommonFrameMetadata},
        pipeline::exception::stack_processing::remap_exception_type_and_module,
        symbol_store::{
            chunk_id::ChunkIdFetcher, hermesmap::HermesMapProvider, proguard::ProguardProvider,
            saving::SymbolSetRecord, sourcemap::SourcemapProvider, Catalog, MockS3Client,
        },
    };

    const PROGUARD_MAP: &str = include_str!("../../../tests/static/proguard/mapping_example.txt");

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_proguard_resolution(db: PgPool) {
        let team_id = 1;
        let mut config = Config::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();

        let map_id = "com.posthog.android.sample@3.0+3".to_string();

        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id,
            set_ref: map_id.clone(),
            storage_ptr: Some(map_id.clone()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some("fake-hash".to_string()),
            last_used: Some(Utc::now()),
        };

        record.save(&db).await.unwrap();

        let mut client = MockS3Client::default();

        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::eq(map_id.clone()), // We set the map id as the storage ptr above, in production it will be a different value with a prefix
            )
            .returning(|_, _| Ok(Some(get_symbol_data_bytes())));

        let client = Arc::new(client);

        let hmp = HermesMapProvider {};
        let hmp = ChunkIdFetcher::new(
            hmp,
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let smp = SourcemapProvider::new(&config);
        let smp = ChunkIdFetcher::new(
            smp,
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let pgp = ChunkIdFetcher::new(
            ProguardProvider {},
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let c = Catalog::new(smp, hmp, pgp);

        let frame = RawJavaFrame {
            module: "a1.d".to_string(),
            filename: Some("SourceFile".to_string()),
            function: "onClick".to_string(),
            lineno: Some(14),
            map_id: Some(map_id),
            method_synthetic: false,
            meta: CommonFrameMetadata::default(),
        };

        let result = remap_exception_type_and_module("a1", "c", team_id, &frame, &c)
            .await
            .unwrap();

        assert_eq!(
            result,
            (
                "com.posthog.android.sample".to_string(),
                "MyCustomException3".to_string()
            )
        );
    }

    fn get_symbol_data_bytes() -> Vec<u8> {
        write_symbol_data(posthog_symbol_data::ProguardMapping {
            content: PROGUARD_MAP.to_string(),
        })
        .unwrap()
    }
}
