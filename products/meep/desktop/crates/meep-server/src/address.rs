use super::Server;
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use std::{
    fs::File,
    path::{Path, PathBuf},
};

#[derive(Default, Serialize, Deserialize)]
pub(super) struct AddressSettings {
    pub(super) public_base_url: Option<String>,
    #[serde(flatten)]
    other: std::collections::BTreeMap<String, serde_json::Value>,
    #[serde(skip)]
    path: Option<PathBuf>,
}

pub(super) fn validate(base: &str) -> Result<String> {
    let url = reqwest::Url::parse(base)?;
    ensure!(
        url.scheme() == "https"
            && url.has_host()
            && url.username().is_empty()
            && url.password().is_none()
            && url.query().is_none()
            && url.fragment().is_none(),
        "Expected a public HTTPS base URL"
    );
    Ok(url.as_str().trim_end_matches('/').to_owned())
}

impl AddressSettings {
    pub(super) fn open(dir: &Path) -> Result<Self> {
        let path = dir.join("settings.json");
        let mut settings: Self = match File::open(&path) {
            Ok(f) => serde_json::from_reader(f)?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Self::default(),
            Err(e) => return Err(e.into()),
        };
        settings.public_base_url = settings
            .public_base_url
            .as_deref()
            .map(validate)
            .transpose()?;
        settings.path = Some(path);
        Ok(settings)
    }
}
impl Server {
    /// Configure the externally reachable HTTPS base for cloud callbacks.
    pub fn with_public_base(mut self, base: &str) -> Result<Self> {
        self.base = Some(validate(base)?);
        self.configure_endpoints();
        Ok(self)
    }

    pub(super) fn configure_endpoints(&mut self) {
        let settings = self.address_settings.lock();
        self.apply_address(settings.public_base_url.as_deref().or(self.base.as_deref()));
    }
    fn apply_address(&self, base: Option<&str>) {
        *self.accounts.public_base.write() = base.map(|base| {
            if self.factory.is_some() || self.owner != self.auth.implicit_owner() {
                format!("{base}/owners/{}", self.owner)
            } else {
                base.to_owned()
            }
        });
    }

    pub(super) fn accepts_mcp_origin(&self, headers: &axum::http::HeaderMap) -> bool {
        let Some(origin) = headers.get("origin") else {
            return true;
        };
        self.accounts
            .public_base
            .read()
            .as_ref()
            .and_then(|base| reqwest::Url::parse(base).ok())
            .is_some_and(|url| {
                origin.to_str().ok() == Some(url.origin().ascii_serialization().as_str())
            })
    }

    pub(super) fn set_address(&self, base: String) -> Result<()> {
        let mut settings = self.address_settings.lock();
        let prior = settings.public_base_url.replace(base.clone());
        if let Some(path) = &settings.path {
            let save = || -> Result<()> {
                let dir = path
                    .parent()
                    .context("The settings file needs a parent directory")?;
                let mut tmp = tempfile::NamedTempFile::new_in(dir)?;
                serde_json::to_writer_pretty(&mut tmp, &*settings)?;
                tmp.as_file().sync_all()?;
                tmp.persist(path)?;
                Ok(())
            };
            if let Err(e) = save() {
                settings.public_base_url = prior;
                return Err(e);
            }
        }
        self.apply_address(Some(&base));
        Ok(())
    }
}
