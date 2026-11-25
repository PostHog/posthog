//! PostHog Desktop's staged and run-scoped attachment upload protocol.
use super::Tasks;
use anyhow::{Context, Result, ensure};
use reqwest::{
    Client, Url,
    multipart::{Form, Part},
    redirect::Policy,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::Path, time::Duration};
use tokio::io::AsyncReadExt;
use uuid::Uuid;

#[derive(Deserialize)]
struct Prepared {
    id: String,
    name: String,
    content_type: String,
    storage_path: String,
    presigned_post: Post,
}
#[derive(Deserialize)]
struct Post {
    url: Url,
    fields: BTreeMap<String, String>,
}
#[derive(Deserialize)]
struct PreparedBatch {
    artifacts: Vec<Prepared>,
}
#[derive(Deserialize)]
struct Receipt {
    id: String,
}
#[derive(Deserialize)]
struct Receipts {
    artifacts: Vec<Receipt>,
}

impl Tasks {
    /// Stage a user-selected file for a new run, or attach it to an existing run.
    pub async fn upload_attachment(
        &self,
        token: &str,
        task: Uuid,
        run: Option<Uuid>,
        path: &Path,
    ) -> Result<String> {
        let name = path
            .file_name()
            .and_then(|p| p.to_str())
            .context("File name is not UTF-8")?;
        let mut file = tokio::fs::File::open(path)
            .await
            .context("Cannot open attachment")?;
        let meta = file.metadata().await?;
        ensure!(meta.is_file(), "Choose a regular file");
        let mime = mime_guess::from_path(name)
            .first_or_octet_stream()
            .to_string();
        let limit = if mime == "application/pdf" { 10 } else { 30 } * 1024 * 1024;
        ensure!(
            meta.len() <= limit,
            "{name} exceeds PostHog's {} MiB limit",
            limit / (1024 * 1024)
        );
        let mut bytes = Vec::with_capacity(meta.len() as usize);
        (&mut file).take(limit + 1).read_to_end(&mut bytes).await?;
        ensure!(
            bytes.len() as u64 == meta.len(),
            "File changed while preparing attachment"
        );
        self.upload_attachment_bytes(token, task, run, name, bytes)
            .await
    }

    /// Stage bytes the person attached elsewhere, such as a view's upload, under `name`.
    pub async fn upload_attachment_bytes(
        &self,
        token: &str,
        task: Uuid,
        run: Option<Uuid>,
        name: &str,
        bytes: Vec<u8>,
    ) -> Result<String> {
        let mime = mime_guess::from_path(name)
            .first_or_octet_stream()
            .to_string();
        let limit = if mime == "application/pdf" { 10 } else { 30 } * 1024 * 1024;
        ensure!(
            bytes.len() as u64 <= limit,
            "{name} exceeds PostHog's {} MiB limit",
            limit / (1024 * 1024)
        );
        let root = match run {
            Some(id) => format!("{task}/runs/{id}/artifacts"),
            None => format!("{task}/staged_artifacts"),
        };
        let upload = json!({
            "name": name,
            "type": "user_attachment",
            "source": "meep",
            "size": bytes.len(),
            "content_type": mime,
        });
        let batch: PreparedBatch = self
            .api
            .post(
                token,
                &format!("{root}/prepare_upload/"),
                json!({"artifacts":[upload]}),
            )
            .await?;
        let [item]: [Prepared; 1] = batch
            .artifacts
            .try_into()
            .map_err(|_| anyhow::anyhow!("Unexpected attachment reservation"))?;
        ensure!(item.name == name, "PostHog reserved a different file name");
        let url = &item.presigned_post.url;
        ensure!(
            url.username().is_empty()
                && url.password().is_none()
                && crate::is_https_or_loopback(url),
            "Invalid upload destination"
        );
        let mut form = Form::new();
        for (key, value) in item.presigned_post.fields {
            form = form.text(key, value);
        }
        form = form.part(
            "file",
            Part::bytes(bytes)
                .file_name(name.to_owned())
                .mime_str(&mime)?,
        );
        // Presigned forms carry their own storage credential. The PostHog bearer stays at its issuer.
        let result = Client::builder()
            .redirect(Policy::none())
            .retry(reqwest::retry::never())
            .timeout(Duration::from_secs(120))
            .build()?
            .post(url.clone())
            .multipart(form)
            .send()
            .await
            .map_err(|_| anyhow::anyhow!("Could not upload the selected attachment"))?;
        ensure!(
            result.status().is_success(),
            "Attachment upload returned HTTP {}",
            result.status().as_u16()
        );
        let details: Value = json!({
            "id": item.id, "name": item.name, "type": "user_attachment",
            "source": "meep", "content_type": item.content_type, "storage_path": item.storage_path,
        });
        let receipt: Receipts = self
            .api
            .post(
                token,
                &format!("{root}/finalize_upload/"),
                json!({"artifacts":[details]}),
            )
            .await?;
        ensure!(
            receipt.artifacts.len() == 1 && receipt.artifacts[0].id == item.id,
            "Unexpected attachment receipt"
        );
        Ok(item.id)
    }
}

/// Largest artifact version read into memory for a preview.
pub const PREVIEW_LIMIT: usize = 25 * 1024 * 1024;

/// The artifact is larger than [`PREVIEW_LIMIT`]; offer a download instead.
#[derive(Debug, thiserror::Error)]
#[error("This file is too large to preview")]
pub struct TooLarge;

/// A file a run recorded in its artifact manifest.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RunArtifact {
    /// Artifact identifier within the run.
    pub id: String,
    /// File name.
    pub name: String,
    /// Classification such as `output`, `artifact`, `plan` or `user_attachment`.
    #[serde(rename = "type", default)]
    pub kind: String,
    /// Size in bytes, when recorded.
    #[serde(default)]
    pub size: Option<u64>,
    /// MIME type, when recorded.
    #[serde(default)]
    pub content_type: Option<String>,
    /// Upload time.
    #[serde(default)]
    pub uploaded_at: Option<String>,
}

/// A run and the files in its artifact manifest.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RunManifest {
    /// PostHog run identifier.
    pub id: Uuid,
    /// Files the run recorded.
    #[serde(default)]
    pub artifacts: Vec<RunArtifact>,
}

#[derive(Deserialize)]
struct ManifestPage {
    results: Vec<RunManifest>,
    next: Option<String>,
}

/// A versioned artifact a run created: a document, spreadsheet, file or delivered message.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LivingArtifact {
    /// Stable artifact identifier.
    pub id: String,
    /// Run that created or now owns it.
    pub run_id: String,
    /// Display name.
    pub name: String,
    /// Format or delivery surface, such as `document` or `slack_canvas`.
    pub artifact_type: String,
    /// `active` or `failed`.
    #[serde(default)]
    pub status: String,
    /// Adapter-specific location, which may carry an external `url`.
    #[serde(default)]
    pub location: Value,
    /// Adapter metadata, including the run file it was made from.
    #[serde(default)]
    pub metadata: Value,
    /// Version a read returns by default.
    #[serde(default)]
    pub current_version: u64,
    /// Chronological version records.
    #[serde(default)]
    pub versions: Vec<Value>,
    /// Last change.
    #[serde(default)]
    pub updated_at: Option<String>,
}

impl LivingArtifact {
    /// The record of the current version.
    pub fn current(&self) -> Option<&Value> {
        self.versions
            .iter()
            .rev()
            .find(|v| v.get("version").and_then(Value::as_u64) == Some(self.current_version))
    }
    /// The run file this artifact was made from, if any.
    pub fn source_artifact_id(&self) -> Option<&str> {
        self.metadata
            .get("source_artifact_id")
            .and_then(Value::as_str)
    }
    /// Where the artifact lives outside PostHog, such as a Slack canvas.
    pub fn external_url(&self) -> Option<&str> {
        self.location.get("url").and_then(Value::as_str)
    }
}

#[derive(Deserialize)]
struct LivingPage {
    artifacts: Vec<LivingArtifact>,
}

impl Tasks {
    /// Every run of a task with its artifact manifest, newest first.
    pub async fn run_manifests(&self, token: &str, task: Uuid) -> Result<Vec<RunManifest>> {
        let mut runs = vec![];
        loop {
            let page: ManifestPage = self
                .api
                .get(
                    token,
                    &format!("{task}/runs/?limit=50&offset={}", runs.len()),
                )
                .await?;
            let done = page.next.is_none() || page.results.is_empty();
            runs.extend(page.results);
            if done || runs.len() >= 500 {
                return Ok(runs);
            }
        }
    }

    /// Versioned artifacts a run created.
    pub async fn living_artifacts(
        &self,
        token: &str,
        task: Uuid,
        run: Uuid,
    ) -> Result<Vec<LivingArtifact>> {
        let page: LivingPage = self
            .api
            .get(token, &format!("{task}/runs/{run}/living_artifacts/"))
            .await?;
        Ok(page.artifacts)
    }

    /// The bytes of one living artifact version.
    pub async fn living_artifact_version(
        &self,
        token: &str,
        task: Uuid,
        run: Uuid,
        artifact: &str,
        version: u64,
    ) -> Result<Vec<u8>> {
        ensure!(
            !artifact.is_empty() && !artifact.contains(['/', '?', '#']),
            "Invalid artifact id"
        );
        let response = self
            .api
            .get_response(
                token,
                &format!("{task}/runs/{run}/living_artifacts/{artifact}/versions/{version}/"),
            )
            .await
            .map_err(|e| match e.downcast_ref::<crate::api::ApiError>() {
                Some(api) if api.status == 413 => TooLarge.into(),
                _ => e,
            })?;
        read_capped(response).await
    }

    /// The bytes of a file in a run's manifest, read through its presigned download.
    pub async fn run_artifact(
        &self,
        token: &str,
        task: Uuid,
        run: Uuid,
        artifact: &str,
    ) -> Result<Vec<u8>> {
        ensure!(
            !artifact.is_empty() && !artifact.contains(['/', '?', '#']),
            "Invalid artifact id"
        );
        let url = self
            .api
            .redirect(
                token,
                &format!("{task}/runs/{run}/artifacts/{artifact}/download/"),
            )
            .await?;
        ensure!(
            url.username().is_empty()
                && url.password().is_none()
                && crate::is_https_or_loopback(&url),
            "Invalid download location"
        );
        // The presigned URL is its own credential. The bearer stays with PostHog.
        let response = Client::builder()
            .redirect(Policy::none())
            .retry(reqwest::retry::never())
            .timeout(Duration::from_secs(120))
            .build()?
            .get(url)
            .send()
            .await
            .context("Could not download the artifact")?;
        ensure!(
            response.status().is_success(),
            "Artifact download returned HTTP {}",
            response.status().as_u16()
        );
        read_capped(response).await
    }
}

async fn read_capped(mut response: reqwest::Response) -> Result<Vec<u8>> {
    if response
        .content_length()
        .is_some_and(|n| n > PREVIEW_LIMIT as u64)
    {
        return Err(TooLarge.into());
    }
    let mut bytes = vec![];
    while let Some(chunk) = response.chunk().await? {
        if bytes.len() + chunk.len() > PREVIEW_LIMIT {
            return Err(TooLarge.into());
        }
        bytes.extend_from_slice(&chunk);
    }
    Ok(bytes)
}
