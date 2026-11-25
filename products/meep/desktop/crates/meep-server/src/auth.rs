use anyhow::{Context, Result};
use meep_connections::SecretStore;
use meep_wire::OwnerId;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::{
    fs::{self, File},
    io::{ErrorKind, Write},
    path::{Path, PathBuf},
};
use subtle::ConstantTimeEq;
use uuid::Uuid;

/// Authenticates device bearer credentials. Webhooks and routines use their own credentials.
pub trait Auth: Send + Sync {
    /// Resolve a device credential to its immutable owner.
    fn owner(&self, token: &str) -> Result<Option<OwnerId>>;
    /// Owner of the original, single-user namespace.
    fn implicit_owner(&self) -> OwnerId;
    /// Check a credential without revealing its owner.
    fn accepts(&self, token: &str) -> Result<bool> {
        Ok(self.owner(token)?.is_some())
    }
}

pub(crate) fn private_dir(dir: &Path) -> Result<()> {
    let mut builder = fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(dir)?;
    Ok(())
}

fn private_write(dir: &Path, name: &str, bytes: &[u8]) -> Result<()> {
    let mut tmp = tempfile::NamedTempFile::new_in(dir)?;
    tmp.write_all(bytes)?;
    tmp.as_file().sync_all()?;
    tmp.persist(dir.join(name))?;
    #[cfg(unix)]
    File::open(dir)?.sync_all()?;
    Ok(())
}

pub(crate) fn matches_secret(left: &str, right: &str) -> bool {
    !left.is_empty() && bool::from(Sha256::digest(left).ct_eq(&Sha256::digest(right)))
}

pub(super) fn fingerprint(token: &str) -> String {
    format!("{:x}", Sha256::digest(token))
}

/// Persistent device credentials in a server data directory.
pub struct DeviceTokens(PathBuf, OwnerId);

#[derive(Serialize, Deserialize)]
struct Registry {
    implicit: OwnerId,
    #[serde(default)]
    tokens_migrated: bool,
    owners: BTreeMap<OwnerId, Option<String>>,
}

impl DeviceTokens {
    /// Open the token directory, creating the desktop's initial token if needed.
    pub fn open(dir: impl AsRef<Path>) -> Result<Self> {
        let mut tokens = Self(dir.as_ref().to_owned(), Uuid::nil());
        private_dir(dir.as_ref())?;
        let _lock = tokens.lock()?;
        let mut registry = match fs::read(tokens.0.join("owners.json")) {
            Ok(data) => serde_json::from_slice::<Registry>(&data)?,
            Err(e) if e.kind() == ErrorKind::NotFound => {
                let implicit = Uuid::new_v4();
                let registry = Registry {
                    implicit,
                    tokens_migrated: false,
                    owners: BTreeMap::from([(implicit, None)]),
                };
                tokens.save_registry(&registry)?;
                registry
            }
            Err(e) => return Err(e.into()),
        };
        anyhow::ensure!(
            registry.owners.contains_key(&registry.implicit),
            "Missing implicit owner"
        );
        tokens.1 = registry.implicit;
        let records = tokens.0.join("tokens");
        private_dir(&records)?;
        for entry in fs::read_dir(&records)? {
            let name = entry?.file_name();
            let name = name.to_str().context("Invalid token fingerprint")?;
            // A process can stop before a temporary atomic write is renamed.
            if name.starts_with(".tmp") {
                continue;
            }
            anyhow::ensure!(
                name.len() == 64 && name.bytes().all(|c| c.is_ascii_hexdigit()),
                "Invalid token record"
            );
            let value = fs::read_to_string(records.join(name))?;
            if value.is_empty() {
                anyhow::ensure!(
                    !registry.tokens_migrated,
                    "Empty owner on a migrated device token"
                );
                private_write(&records, name, tokens.1.to_string().as_bytes())?;
            } else {
                anyhow::ensure!(
                    registry.owners.contains_key(&value.parse()?),
                    "Unknown token owner"
                );
            }
        }
        let bootstrap = tokens.0.join("device-token");
        // Publish the desktop credential before its digest, so initialization is recoverable.
        if !bootstrap.exists() && tokens.list()?.is_empty() {
            private_write(&tokens.0, "device-token", Self::generate().as_bytes())?;
        }
        if bootstrap.exists() {
            let token = fs::read_to_string(bootstrap)?;
            anyhow::ensure!(!token.trim().is_empty(), "Empty desktop credential");
            match tokens.owner(token.trim())? {
                None => tokens.record(token.trim(), tokens.1)?,
                Some(id) => anyhow::ensure!(id == tokens.1, "Conflicting desktop token owner"),
            }
        }
        if !registry.tokens_migrated {
            registry.tokens_migrated = true;
            tokens.save_registry(&registry)?;
        }
        Ok(tokens)
    }

    fn lock(&self) -> Result<File> {
        let file = File::options()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(self.0.join("tokens.lock"))?;
        file.lock()?;
        Ok(file)
    }
    fn generate() -> String {
        format!(
            "meep_{}{}",
            Uuid::new_v4().simple(),
            Uuid::new_v4().simple()
        )
    }
    fn record(&self, token: &str, owner: OwnerId) -> Result<()> {
        let dir = self.0.join("tokens");
        private_dir(&dir)?;
        private_write(&dir, &fingerprint(token), owner.to_string().as_bytes())
    }

    /// Create an additional credential and return its bearer value once.
    pub fn create(&self) -> Result<String> {
        self.create_for(self.1)
    }

    fn registry(&self) -> Result<Registry> {
        Ok(serde_json::from_slice(&fs::read(
            self.0.join("owners.json"),
        )?)?)
    }
    fn save_registry(&self, registry: &Registry) -> Result<()> {
        private_write(&self.0, "owners.json", &serde_json::to_vec(registry)?)
    }
    /// List registered owners and their optional display labels.
    pub fn owners(&self) -> Result<BTreeMap<OwnerId, Option<String>>> {
        Ok(self.registry()?.owners)
    }
    /// Allocate a new, empty user namespace.
    pub fn add_owner(&self, label: Option<String>) -> Result<OwnerId> {
        let _lock = self.lock()?;
        let mut registry = self.registry()?;
        let id = Uuid::new_v4();
        registry.owners.insert(id, label);
        self.save_registry(&registry)?;
        Ok(id)
    }
    /// Issue a device credential for a registered owner.
    pub fn create_for(&self, owner: OwnerId) -> Result<String> {
        let _lock = self.lock()?;
        anyhow::ensure!(self.owners()?.contains_key(&owner), "Unknown owner");
        let token = Self::generate();
        self.record(&token, owner)?;
        Ok(token)
    }

    /// Revoke exactly one fingerprint returned by list, including a desktop credential.
    pub fn revoke(&self, id: &str) -> Result<()> {
        anyhow::ensure!(
            id.len() == 16 && id.bytes().all(|b| b.is_ascii_hexdigit()),
            "Invalid device fingerprint"
        );
        let _lock = self.lock()?;
        let dir = self.0.join("tokens");
        let mut paths = Vec::new();
        for entry in fs::read_dir(&dir)? {
            let entry = entry?;
            if entry
                .file_name()
                .to_str()
                .is_some_and(|s| s.len() == 64 && s.starts_with(id))
            {
                paths.push(entry.path());
            }
        }
        let [path] = paths.as_slice() else {
            anyhow::bail!("Unknown or ambiguous device fingerprint")
        };
        let bootstrap = self.0.join("device-token");
        if bootstrap.try_exists()?
            && fingerprint(fs::read_to_string(&bootstrap)?.trim()).starts_with(id)
        {
            fs::remove_file(bootstrap)?;
            File::open(&self.0)?.sync_all()?;
        }
        fs::remove_file(path)?;
        File::open(dir)?.sync_all()?;
        Ok(())
    }

    /// List stable token fingerprints, suitable for display.
    pub fn list(&self) -> Result<Vec<String>> {
        let entries = match fs::read_dir(self.0.join("tokens")) {
            Ok(entries) => entries,
            Err(e) if e.kind() == ErrorKind::NotFound => return Ok(vec![]),
            Err(e) => return Err(e.into()),
        };
        let mut ids = vec![];
        for entry in entries {
            let name = entry?.file_name();
            if let Some(s) = name
                .to_str()
                .filter(|s| s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()))
            {
                ids.push(s[..16].to_owned());
            }
        }
        ids.sort();
        Ok(ids)
    }
}
impl Auth for DeviceTokens {
    fn implicit_owner(&self) -> OwnerId {
        self.1
    }
    fn owner(&self, token: &str) -> Result<Option<OwnerId>> {
        match fs::read_to_string(self.0.join("tokens").join(fingerprint(token))) {
            Ok(value) => Ok(Some(value.parse()?)),
            Err(e) if e.kind() == ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e.into()),
        }
    }
}

/// A file-backed SecretStore with atomic owner-only writes.
pub struct FileSecrets(PathBuf);
impl FileSecrets {
    /// Open or create a directory for credentials.
    pub fn open(dir: impl AsRef<Path>) -> Result<Self> {
        private_dir(dir.as_ref())?;
        Ok(Self(dir.as_ref().to_owned()))
    }
    fn key(connection: &str, name: &str) -> Result<String> {
        let key = serde_json::to_string(&(connection, name))?;
        Ok(fingerprint(&key))
    }
}
impl SecretStore for FileSecrets {
    fn get(&self, connection: &str, name: &str) -> Result<Option<String>> {
        match fs::read_to_string(self.0.join(Self::key(connection, name)?)) {
            Ok(value) => Ok(Some(value)),
            Err(e) if e.kind() == ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e).context("read connection credential"),
        }
    }
    fn set(&mut self, connection: &str, name: &str, value: &str) -> Result<()> {
        private_write(&self.0, &Self::key(connection, name)?, value.as_bytes())
    }
    fn delete(&mut self, connection: &str, name: &str) -> Result<()> {
        match fs::remove_file(self.0.join(Self::key(connection, name)?)) {
            Err(e) if e.kind() != ErrorKind::NotFound => Err(e.into()),
            _ => Ok(()),
        }
    }
}
