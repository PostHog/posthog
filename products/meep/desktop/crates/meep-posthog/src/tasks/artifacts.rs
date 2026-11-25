//! PostHog Desktop's staged and run-scoped attachment upload protocol.
use super::Tasks;
use anyhow::{Context, Result, ensure};
use reqwest::{
    Client, Url,
    multipart::{Form, Part},
    redirect::Policy,
};
use serde::Deserialize;
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
