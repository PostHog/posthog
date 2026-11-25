//! Pure URL validation shared by renderers; grants no host capability.
use anyhow::{Context, Result, bail};

pub fn web_url(value: &str) -> Result<()> {
    let url = url::Url::parse(value).context("Invalid URL")?;
    if !matches!(url.scheme(), "http" | "https" | "mailto")
        || !url.username().is_empty()
        || url.password().is_some()
    {
        bail!("Only HTTP, HTTPS and mailto links are allowed");
    }
    Ok(())
}
