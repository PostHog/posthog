//! Sources accepted by the native Image element and its broker service.
use anyhow::{Context, Result, bail};
use serde_json::{Value, json};
use url::Url;

pub const MAX_BYTES: usize = 8 * 1024 * 1024;
pub const MAX_DOMAINS: usize = 128;
pub const DISCLOSURE: &str = "This view can load images from this domain until you remove its approval in Security & Trust. The site receives your IP address and the requested image URL.";

/// Turn a hostname typed into Settings into the same key used for image URLs.
pub fn photo_domain(raw: &str) -> Result<String> {
    let raw = raw.trim();
    if raw.len() > 1024
        || raw.contains(['/', '\\', ':', '@', '?', '#', '%'])
        || raw.chars().any(|c| c.is_whitespace() || c.is_control())
    {
        bail!("Enter a hostname such as images.example.com.");
    }
    let url = remote_url(&format!("https://{raw}/"))
        .context("Enter a public hostname such as images.example.com.")?;
    Ok(url.domain().unwrap().to_owned())
}

pub fn approval_title(domain: &str) -> String {
    format!("Allow images from {domain}?")
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum ImageSource {
    Remote(Url),
    Local { id: String, path: Option<String> },
}

impl ImageSource {
    pub fn parse(value: &Value) -> Result<Self> {
        if let Some(url) = value.as_str() {
            return Ok(Self::Remote(remote_url(url)?));
        }
        let id = value["id"]
            .as_str()
            .filter(|id| !id.is_empty() && id.len() <= 128 && !id.chars().any(char::is_control))
            .context(
                "Choose an image with the file or folder picker, or use an HTTPS image URL.",
            )?;
        let path = match &value["path"] {
            Value::Null => None,
            Value::String(path) if path.len() <= 1024 => Some(path.clone()),
            _ => bail!("Use a relative image path within the chosen folder."),
        };
        Ok(Self::Local {
            id: id.to_owned(),
            path,
        })
    }

    pub fn to_value(&self) -> Value {
        match self {
            Self::Remote(url) => json!(url.as_str()),
            Self::Local { id, path } => json!({"id":id,"path":path}),
        }
    }

    pub fn domain(&self) -> Option<&str> {
        match self {
            Self::Remote(url) => url.domain(),
            Self::Local { .. } => None,
        }
    }
}

pub fn remote_url(raw: &str) -> Result<Url> {
    let mut url = (raw.len() <= 8192)
        .then(|| Url::parse(raw).ok())
        .flatten()
        .context("Use a valid HTTPS image URL.")?;
    if url.scheme() != "https"
        || url.port().is_some()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        bail!("Image links require HTTPS on the standard port and no credentials.");
    }
    let host = url
        .domain()
        .context("Image links require a public domain.")?;
    let host = host.strip_suffix('.').unwrap_or(host);
    if !valid_domain(host) {
        bail!("Image links require a public domain.");
    }
    let host = host.to_owned();
    url.set_host(Some(&host))
        .map_err(|_| anyhow::anyhow!("Invalid image domain."))?;
    url.set_fragment(None);
    Ok(url)
}

pub fn valid_domain(host: &str) -> bool {
    host.len() <= 253
        && host.contains('.')
        && !host.ends_with(".localhost")
        && !host.ends_with(".local")
        && !host.ends_with(".internal")
        && host
            .rsplit('.')
            .next()
            .is_some_and(|label| label.bytes().any(|c| c.is_ascii_lowercase()))
        && host.split('.').all(|label| {
            !label.is_empty()
                && label.len() <= 63
                && !label.starts_with('-')
                && !label.ends_with('-')
                && label
                    .bytes()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn photo_rules_use_the_same_exact_hostname_as_image_urls() {
        for input in [" Images.Example.COM. ", "bücher.example"] {
            let parsed = photo_domain(input).unwrap();
            let url = remote_url(&format!("https://{}/photo.jpg", input.trim())).unwrap();
            assert_eq!(url.domain(), Some(parsed.as_str()));
        }
        for input in [
            "",
            "https://example.com",
            "example.com/photo",
            "*.example.com",
            "127.0.0.1",
            "a.local",
            "a.example:443",
            "a\\b.example",
            "%65xample.com",
        ] {
            assert!(photo_domain(input).is_err(), "{input}");
        }
    }
}
