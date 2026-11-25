use anyhow::{Context, Result};
use meep_topic::TopicId;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    fs::{self, File},
    path::{Path, PathBuf},
};

/// A file operation ID was previously committed with different contents.
#[derive(Debug, thiserror::Error)]
#[error("File operation ID was already used for different contents. Use a new ID for a new edit.")]
pub struct FileOperationConflict;

/// One immutable version of a logical topic file.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Blob {
    /// Logical file name.
    pub name: String,
    /// One-based version within this topic and file name.
    pub revision: u64,
    /// Unmodified file contents.
    pub bytes: Vec<u8>,
}

/// A new or replayed immutable revision and, for a competing edit, the current head.
pub struct FileWrite {
    /// Revision containing the submitted bytes.
    pub revision: Blob,
    /// Present when the bytes were retained as a competing version for review.
    pub competing_with: Option<u64>,
}

/// Revisioned files scoped by topic. Names are logical keys and may contain slashes.
pub trait Blobs: Send + Sync {
    /// Append an idempotent deletion marker and return its revision.
    fn delete(&self, topic: TopicId, name: &str, key: uuid::Uuid) -> Result<u64>;
    /// Remove every physical revision of a deleted topic.
    fn purge(&self, topic: TopicId) -> Result<()>;
    /// Append an immutable revision.
    fn put(&self, topic: TopicId, name: &str, bytes: &[u8]) -> Result<Blob>;
    /// Append once per file and operation ID. A replay returns the original revision.
    fn put_once(&self, topic: TopicId, name: &str, bytes: &[u8], key: uuid::Uuid) -> Result<Blob>;
    /// Compare the observed base (zero for a new file) under the same lock as the append.
    /// A stale edit receives its own immutable revision without advancing the head.
    fn put_based(
        &self,
        _topic: TopicId,
        _name: &str,
        _bytes: &[u8],
        _key: uuid::Uuid,
        _base: u64,
    ) -> Result<FileWrite> {
        anyhow::bail!("This file store does not support conditional writes")
    }
    /// Publish the selected bytes only if the reviewed head still matches.
    fn publish_choice(
        &self,
        _topic: TopicId,
        _name: &str,
        _bytes: &[u8],
        _key: uuid::Uuid,
        _current: u64,
    ) -> Result<Blob> {
        anyhow::bail!("This file store does not support revision choices")
    }
    /// Current tombstone revisions, for reconciling a crash between file and topic writes.
    fn deleted_heads(&self, topic: TopicId) -> Result<BTreeMap<String, u64>>;
    /// Enumerate immutable alternatives by path, using revision metadata only.
    fn alternatives(&self, _topic: TopicId) -> Result<BTreeMap<String, Vec<u64>>> {
        Ok(BTreeMap::new())
    }
    /// Read one revision, or the current head with None.
    fn get(&self, topic: TopicId, name: &str, revision: Option<u64>) -> Result<Option<Blob>>;
    /// Enumerate a file's revisions oldest first.
    fn history(&self, topic: TopicId, name: &str) -> Result<Vec<Blob>>;
    /// Enumerate logical names without loading the contents.
    fn names(&self, topic: TopicId) -> Result<Vec<String>>;
    /// List each file's latest revision in name order.
    fn list(&self, topic: TopicId) -> Result<Vec<Blob>>;
}

#[derive(Clone, Copy)]
enum FileBase {
    Delete,
    Unconditional,
    Edited(u64),
    Reviewed(u64),
}

impl FileBase {
    fn competes(self, head: u64, latest: u64, deleted: u64) -> Result<bool> {
        match self {
            Self::Delete | Self::Unconditional => Ok(false),
            Self::Edited(base) => {
                anyhow::ensure!(
                    base <= latest && (base == 0 || base > deleted),
                    UnknownFileBase
                );
                Ok(base != head)
            }
            Self::Reviewed(base) => {
                anyhow::ensure!(head == base, "The file changed. Open the current review.");
                Ok(false)
            }
        }
    }
}

struct MemoryRevision {
    blob: Blob,
    key: Option<uuid::Uuid>,
    branch: bool,
    deleted: bool,
}

type Files = BTreeMap<String, Vec<MemoryRevision>>;

/// Revisioned files kept in memory for tests and fixture hosts.
#[derive(Default)]
pub struct MemoryBlobs {
    files: Mutex<BTreeMap<TopicId, Files>>,
}
impl MemoryBlobs {
    fn append(
        &self,
        t: TopicId,
        name: &str,
        bytes: &[u8],
        key: Option<uuid::Uuid>,
        base: FileBase,
    ) -> Result<FileWrite> {
        let mut files = self.files.lock();
        let versions = files
            .entry(t)
            .or_default()
            .entry(name.to_owned())
            .or_default();
        let head = versions
            .iter()
            .rev()
            .find(|r| !r.branch)
            .map_or(0, |r| if r.deleted { 0 } else { r.blob.revision });
        if let Some(old) = key.and_then(|k| versions.iter().find(|r| r.key == Some(k))) {
            anyhow::ensure!(
                old.deleted == matches!(base, FileBase::Delete) && old.blob.bytes == bytes,
                FileOperationConflict
            );
            return Ok(FileWrite {
                revision: old.blob.clone(),
                competing_with: old.branch.then_some(head),
            });
        }
        let branch = base.competes(
            head,
            u64::try_from(versions.len())?,
            versions
                .iter()
                .rev()
                .find(|v| v.deleted)
                .map_or(0, |v| v.blob.revision),
        )? && versions
            .iter()
            .rev()
            .find(|r| !r.branch)
            .is_some_and(|r| r.blob.bytes != bytes);
        let blob = Blob {
            name: name.into(),
            revision: u64::try_from(versions.len())?
                .checked_add(1)
                .context("file revision exhausted")?,
            bytes: bytes.into(),
        };
        versions.push(MemoryRevision {
            blob: blob.clone(),
            key,
            branch,
            deleted: matches!(base, FileBase::Delete),
        });
        Ok(FileWrite {
            revision: blob,
            competing_with: branch.then_some(head),
        })
    }
}
impl Blobs for MemoryBlobs {
    fn deleted_heads(&self, topic: TopicId) -> Result<BTreeMap<String, u64>> {
        Ok(self
            .files
            .lock()
            .get(&topic)
            .into_iter()
            .flatten()
            .filter_map(|(name, versions)| {
                let head = versions.iter().rev().find(|r| !r.branch)?;
                head.deleted.then(|| (name.clone(), head.blob.revision))
            })
            .collect())
    }
    fn purge(&self, topic: TopicId) -> Result<()> {
        self.files.lock().remove(&topic);
        Ok(())
    }
    fn delete(&self, topic: TopicId, name: &str, key: uuid::Uuid) -> Result<u64> {
        Ok(self
            .append(topic, name, &[], Some(key), FileBase::Delete)?
            .revision
            .revision)
    }

    fn put(&self, t: TopicId, n: &str, b: &[u8]) -> Result<Blob> {
        Ok(self
            .append(t, n, b, None, FileBase::Unconditional)?
            .revision)
    }
    fn put_once(&self, t: TopicId, n: &str, b: &[u8], key: uuid::Uuid) -> Result<Blob> {
        Ok(self
            .append(t, n, b, Some(key), FileBase::Unconditional)?
            .revision)
    }
    fn publish_choice(
        &self,
        t: TopicId,
        n: &str,
        b: &[u8],
        key: uuid::Uuid,
        head: u64,
    ) -> Result<Blob> {
        Ok(self
            .append(t, n, b, Some(key), FileBase::Reviewed(head))?
            .revision)
    }
    fn put_based(
        &self,
        t: TopicId,
        n: &str,
        b: &[u8],
        key: uuid::Uuid,
        base: u64,
    ) -> Result<FileWrite> {
        self.append(t, n, b, Some(key), FileBase::Edited(base))
    }
    fn get(&self, t: TopicId, n: &str, rev: Option<u64>) -> Result<Option<Blob>> {
        Ok(self
            .files
            .lock()
            .get(&t)
            .and_then(|f| f.get(n))
            .and_then(|v| {
                v.iter()
                    .rev()
                    .find(|r| rev.map_or(!r.branch, |id| r.blob.revision == id))
                    .filter(|r| !r.deleted)
            })
            .map(|r| r.blob.clone()))
    }
    fn alternatives(&self, topic: TopicId) -> Result<BTreeMap<String, Vec<u64>>> {
        let mut paths = BTreeMap::new();
        if let Some(files) = self.files.lock().get(&topic) {
            for (name, versions) in files {
                let mut branches: Vec<_> = versions
                    .iter()
                    .rev()
                    .take_while(|r| !r.deleted)
                    .filter(|r| r.branch)
                    .map(|r| r.blob.revision)
                    .collect();
                branches.reverse();
                if !branches.is_empty() {
                    paths.insert(name.clone(), branches);
                }
            }
        }
        Ok(paths)
    }
    fn history(&self, t: TopicId, n: &str) -> Result<Vec<Blob>> {
        Ok(self
            .files
            .lock()
            .get(&t)
            .and_then(|f| f.get(n))
            .into_iter()
            .flatten()
            .map(|r| r.blob.clone())
            .collect())
    }
    fn names(&self, t: TopicId) -> Result<Vec<String>> {
        Ok(self
            .files
            .lock()
            .get(&t)
            .into_iter()
            .flat_map(|f| {
                f.iter()
                    .filter(|(_, v)| {
                        v.iter()
                            .rev()
                            .find(|r| !r.branch)
                            .is_some_and(|r| !r.deleted)
                    })
                    .map(|(name, _)| name.clone())
            })
            .collect())
    }
    fn list(&self, t: TopicId) -> Result<Vec<Blob>> {
        Ok(self
            .files
            .lock()
            .get(&t)
            .into_iter()
            .flat_map(|f| f.values())
            .filter_map(|v| v.iter().rev().find(|r| !r.branch).filter(|r| !r.deleted))
            .map(|r| r.blob.clone())
            .collect())
    }
}

#[derive(Clone, Copy, Ord, PartialOrd, PartialEq, Eq)]
struct Version {
    number: u64,
    key: Option<uuid::Uuid>,
    branch: bool,
    deleted: bool,
}
impl Version {
    fn filename(self) -> String {
        let key = self.key.map_or_else(String::new, |k| format!(".{k}"));
        let suffix = if self.deleted {
            ".deleted.blob"
        } else if self.branch {
            ".branch.blob"
        } else {
            ".blob"
        };
        format!("{}{key}{suffix}", self.number)
    }
}
/// A directory of immutable binary revisions. Logical names are stored as metadata;
/// the filesystem path uses a fixed-size hash scoped to the topic.
pub struct DirBlobs(PathBuf);

impl DirBlobs {
    fn heads(&self, topic: TopicId) -> Result<BTreeMap<String, Version>> {
        let entries = match fs::read_dir(self.0.join(topic.to_string())) {
            Ok(entries) => entries,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(BTreeMap::new()),
            Err(e) => return Err(e.into()),
        };
        let mut heads = BTreeMap::new();
        for entry in entries {
            let dir = entry?.path();
            if let Some(head) = Self::revisions(&dir)?.iter().rev().find(|r| !r.branch) {
                let name = fs::read_to_string(dir.join("name"))?;
                heads.insert(name, *head);
            }
        }
        Ok(heads)
    }

    /// Open or create a topic file directory.
    pub fn open(root: impl AsRef<Path>) -> Result<Self> {
        fs::create_dir_all(root.as_ref())?;
        Ok(Self(root.as_ref().canonicalize()?))
    }

    fn path(&self, topic: TopicId, name: &str) -> PathBuf {
        use sha2::{Digest, Sha256};
        let digest = Sha256::digest(name.as_bytes());
        self.0.join(topic.to_string()).join(format!("{digest:x}"))
    }

    fn put_atomic(dir: &Path, path: &Path, bytes: &[u8]) -> Result<()> {
        use std::io::Write;
        let mut tmp = tempfile::NamedTempFile::new_in(dir)?;
        tmp.write_all(bytes)?;
        tmp.as_file().sync_all()?;
        tmp.persist(path)?;
        #[cfg(unix)]
        File::open(dir)?.sync_all()?;
        Ok(())
    }

    fn revisions(dir: &Path) -> Result<Vec<Version>> {
        let mut revisions = Vec::new();
        let entries = match fs::read_dir(dir) {
            Ok(entries) => entries,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(revisions),
            Err(e) => return Err(e.into()),
        };
        for entry in entries {
            let entry = entry?;
            let filename = entry.file_name();
            if let Some(stem) = filename.to_str().and_then(|s| s.strip_suffix(".blob")) {
                let deleted = stem.ends_with(".deleted");
                let stem = stem.strip_suffix(".deleted").unwrap_or(stem);
                let (stem, branch) = stem
                    .strip_suffix(".branch")
                    .map_or((stem, false), |s| (s, true));
                let (rev, key) = stem
                    .split_once('.')
                    .map_or((stem, None), |(r, k)| (r, Some(k)));
                revisions.push(Version {
                    deleted,
                    number: rev.parse()?,
                    key: key.map(str::parse).transpose()?,
                    branch,
                });
            }
        }
        revisions.sort_unstable();
        Ok(revisions)
    }

    fn read(dir: &Path, name: &str, version: Version) -> Result<Option<Blob>> {
        match fs::read(dir.join(version.filename())) {
            Ok(bytes) => Ok(Some(Blob {
                name: name.into(),
                revision: version.number,
                bytes,
            })),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e.into()),
        }
    }
}

impl DirBlobs {
    fn append(
        &self,
        topic: TopicId,
        name: &str,
        bytes: &[u8],
        key: Option<uuid::Uuid>,
        base: FileBase,
    ) -> Result<FileWrite> {
        let dir = self.path(topic, name);
        fs::create_dir_all(&dir)?;
        let lock = File::options()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(dir.join("write.lock"))?;
        lock.lock()?;
        let metadata = dir.join("name");
        match fs::read_to_string(&metadata) {
            Ok(stored) => anyhow::ensure!(stored == name, "topic file name collision"),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                Self::put_atomic(&dir, &metadata, name.as_bytes())?;
                #[cfg(unix)]
                {
                    File::open(self.0.join(topic.to_string()))?.sync_all()?;
                    File::open(&self.0)?.sync_all()?;
                }
            }
            Err(e) => return Err(e.into()),
        }
        let revisions = Self::revisions(&dir)?;
        let head = revisions
            .iter()
            .rev()
            .find(|r| !r.branch)
            .map_or(0, |r| if r.deleted { 0 } else { r.number });
        if key.is_some()
            && let Some(&prior) = revisions.iter().find(|r| r.key == key)
        {
            let blob = Self::read(&dir, name, prior)?.context("missing file revision")?;
            anyhow::ensure!(
                prior.deleted == matches!(base, FileBase::Delete) && blob.bytes == bytes,
                FileOperationConflict
            );
            return Ok(FileWrite {
                revision: blob,
                competing_with: prior.branch.then_some(head),
            });
        }
        let revision = revisions
            .last()
            .map(|v| v.number)
            .unwrap_or(0)
            .checked_add(1)
            .context("file revision exhausted")?;
        let branch = if base.competes(
            head,
            revision - 1,
            revisions
                .iter()
                .rev()
                .find(|v| v.deleted)
                .map_or(0, |v| v.number),
        )? {
            let version = revisions
                .iter()
                .rev()
                .find(|r| !r.branch)
                .context("missing file head")?;
            Self::read(&dir, name, *version)?
                .context("missing file head")?
                .bytes
                != bytes
        } else {
            false
        };
        let version = Version {
            deleted: matches!(base, FileBase::Delete),
            number: revision,
            key,
            branch,
        };
        Self::put_atomic(&dir, &dir.join(version.filename()), bytes)?;
        Ok(FileWrite {
            revision: Blob {
                name: name.into(),
                revision,
                bytes: bytes.into(),
            },
            competing_with: version.branch.then_some(head),
        })
    }
}
impl Blobs for DirBlobs {
    fn deleted_heads(&self, topic: TopicId) -> Result<BTreeMap<String, u64>> {
        Ok(self
            .heads(topic)?
            .into_iter()
            .filter(|(_, head)| head.deleted)
            .map(|(name, head)| (name, head.number))
            .collect())
    }
    fn purge(&self, topic: TopicId) -> Result<()> {
        match fs::remove_dir_all(self.0.join(topic.to_string())) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
            r => Ok(r?),
        }
    }
    fn delete(&self, topic: TopicId, name: &str, key: uuid::Uuid) -> Result<u64> {
        Ok(self
            .append(topic, name, &[], Some(key), FileBase::Delete)?
            .revision
            .revision)
    }

    fn put(&self, topic: TopicId, name: &str, bytes: &[u8]) -> Result<Blob> {
        Ok(self
            .append(topic, name, bytes, None, FileBase::Unconditional)?
            .revision)
    }
    fn put_once(&self, topic: TopicId, name: &str, bytes: &[u8], key: uuid::Uuid) -> Result<Blob> {
        Ok(self
            .append(topic, name, bytes, Some(key), FileBase::Unconditional)?
            .revision)
    }
    fn publish_choice(
        &self,
        t: TopicId,
        n: &str,
        b: &[u8],
        key: uuid::Uuid,
        head: u64,
    ) -> Result<Blob> {
        Ok(self
            .append(t, n, b, Some(key), FileBase::Reviewed(head))?
            .revision)
    }
    fn put_based(
        &self,
        t: TopicId,
        n: &str,
        b: &[u8],
        key: uuid::Uuid,
        base: u64,
    ) -> Result<FileWrite> {
        self.append(t, n, b, Some(key), FileBase::Edited(base))
    }
    fn get(&self, topic: TopicId, name: &str, revision: Option<u64>) -> Result<Option<Blob>> {
        let dir = self.path(topic, name);
        match Self::revisions(&dir)?
            .into_iter()
            .rev()
            .find(|r| revision.map_or(!r.branch, |wanted| wanted == r.number))
        {
            Some(record) if record.deleted => Ok(None),
            Some(record) => Self::read(&dir, name, record),
            None => Ok(None),
        }
    }
    fn alternatives(&self, topic: TopicId) -> Result<BTreeMap<String, Vec<u64>>> {
        let mut paths = BTreeMap::new();
        for name in self.names(topic)? {
            let mut branches: Vec<_> = Self::revisions(&self.path(topic, &name))?
                .into_iter()
                .rev()
                .take_while(|r| !r.deleted)
                .filter(|r| r.branch)
                .map(|r| r.number)
                .collect();
            branches.reverse();
            if !branches.is_empty() {
                paths.insert(name, branches);
            }
        }
        Ok(paths)
    }
    fn history(&self, topic: TopicId, name: &str) -> Result<Vec<Blob>> {
        let dir = self.path(topic, name);
        Self::revisions(&dir)?
            .into_iter()
            .map(|r| Self::read(&dir, name, r)?.context("missing file revision"))
            .collect()
    }
    fn names(&self, topic: TopicId) -> Result<Vec<String>> {
        Ok(self
            .heads(topic)?
            .into_iter()
            .filter(|(_, head)| !head.deleted)
            .map(|(name, _)| name)
            .collect())
    }
    fn list(&self, topic: TopicId) -> Result<Vec<Blob>> {
        self.names(topic)?
            .into_iter()
            .map(|n| self.get(topic, &n, None)?.context("missing file head"))
            .collect()
    }
}

/// The submitted edit refers to a revision the server has never stored.
#[derive(Debug, thiserror::Error)]
#[error("Unknown file base revision")]
pub struct UnknownFileBase;
