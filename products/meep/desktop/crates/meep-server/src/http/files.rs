use super::*;

pub(super) async fn files(
    Extension(a): Extension<App>,
    Path(topic): Path<TopicId>,
    Query(q): Query<ListQuery>,
) -> Result<Response> {
    a.s.accounts
        .jobs
        .clone()
        .spawn_blocking(move || {
            a.s.engine.read_topic(topic, |_| ())?;
            Ok(q.page(
                a.s.engine.blobs().names(topic).map_err(Failure::internal)?,
                |v| v,
            ))
        })
        .await
        .map_err(Failure::internal)?
}

#[derive(Deserialize, Serialize)]
pub(super) struct Revision {
    revision: Option<u64>,
}
fn file_response(blob: meep_engine::Blob) -> Response {
    (
        [
            ("x-meep-revision", blob.revision.to_string()),
            ("content-type", "application/octet-stream".into()),
        ],
        blob.bytes,
    )
        .into_response()
}
pub(super) async fn read_file(
    Extension(a): Extension<App>,
    Path((topic, path)): Path<(TopicId, String)>,
    Query(q): Query<Revision>,
) -> Result<Response> {
    a.s.accounts
        .jobs
        .clone()
        .spawn_blocking(move || {
            a.s.engine.read_topic(topic, |_| ())?;
            let blob =
                a.s.engine
                    .blobs()
                    .get(topic, &path, q.revision)
                    .map_err(Failure::internal)?
                    .ok_or_else(|| {
                        Failure(
                            StatusCode::NOT_FOUND,
                            "unknown_file",
                            "File revision does not exist".into(),
                        )
                    })?;
            Ok(file_response(blob))
        })
        .await
        .map_err(Failure::internal)?
}
pub(super) async fn write_file(
    Extension(a): Extension<App>,
    Path((topic, path)): Path<(TopicId, String)>,
    headers: HeaderMap,
    bytes: Bytes,
) -> Result<Response> {
    let key = headers
        .get("idempotency-key")
        .map(|h| {
            h.to_str()
                .ok()
                .and_then(|v| v.parse().ok())
                .ok_or_else(|| Failure::bad("Invalid file operation ID"))
        })
        .transpose()?;
    let base = headers
        .get("x-meep-base-revision")
        .map(|v| {
            v.to_str()
                .ok()
                .and_then(|s| s.parse::<u64>().ok())
                .ok_or_else(|| Failure::bad("Invalid base revision"))
        })
        .transpose()?;
    let write =
        a.s.engine
            .write_file(
                topic,
                path,
                bytes.to_vec(),
                key.unwrap_or_else(uuid::Uuid::new_v4),
                base,
            )
            .await
            .map_err(|error| {
                if let EngineError::Integration(ref cause) = error
                    && cause.is::<meep_engine::UnknownFileBase>()
                {
                    return Failure::bad(&cause.to_string());
                }
                if let EngineError::Integration(ref cause) = error
                    && cause.is::<meep_engine::FileOperationConflict>()
                {
                    return Failure(
                        StatusCode::CONFLICT,
                        "file_operation_conflict",
                        cause.to_string(),
                    );
                }
                Failure::from(error)
            })?;
    let mut response = file_response(write.revision);
    if let Some(head) = write.competing_with {
        response
            .headers_mut()
            .insert("x-meep-conflict-head", head.into());
    }
    Ok(response)
}

fn artifact_failure(error: anyhow::Error) -> Failure {
    if error.is::<meep_posthog::tasks::artifacts::TooLarge>() {
        return Failure(
            StatusCode::PAYLOAD_TOO_LARGE,
            "artifact_too_large",
            error.to_string(),
        );
    }
    if let Some(engine) = error.downcast_ref::<EngineError>()
        && matches!(engine, EngineError::UnknownTopic(_))
    {
        return Failure(StatusCode::NOT_FOUND, "unknown_topic", engine.to_string());
    }
    // 4xx: PostHog being unreachable is not this server being offline.
    Failure(
        StatusCode::FAILED_DEPENDENCY,
        "artifacts_unavailable",
        format!("{error:#}"),
    )
}

/// Artifacts the topic's task runs produced, listed live from PostHog.
pub(super) async fn artifacts(
    Extension(a): Extension<App>,
    Path(topic): Path<TopicId>,
) -> Result<Json<Vec<meep_wire::TaskArtifact>>> {
    a.s.engine.read_topic(topic, |_| ())?;
    crate::artifacts::list(&a.s, topic)
        .await
        .map(Json)
        .map_err(artifact_failure)
}

#[derive(Deserialize)]
pub(super) struct ArtifactVersion {
    #[serde(default)]
    version: u64,
}

/// One artifact version's bytes, proxied from PostHog without being stored.
pub(super) async fn artifact(
    Extension(a): Extension<App>,
    Path((topic, task, run, artifact)): Path<(TopicId, meep_topic::TaskId, uuid::Uuid, String)>,
    Query(q): Query<ArtifactVersion>,
) -> Result<Response> {
    a.s.engine.read_topic(topic, |_| ())?;
    let bytes = crate::artifacts::read(&a.s, topic, task, run, &artifact, q.version)
        .await
        .map_err(artifact_failure)?;
    Ok(([("content-type", "application/octet-stream")], bytes).into_response())
}
