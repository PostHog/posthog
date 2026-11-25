#![doc = include_str!("../README.md")]

use anyhow::{Context, Result, ensure};
pub use cap_std::fs::Dir;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::fs::{self, File};
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::{fmt, str::FromStr};
use tempfile::{Builder, NamedTempFile};
use uuid::Uuid;

// Existing catalogs use these file names. All writers must use the same lock.
const RECORD_FILE: &str = "space.json";
const LOCK_FILE: &str = "space.lock";

/// Save this ID to open the same topic after a restart.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(transparent)]
pub struct TopicId(Uuid);

impl fmt::Display for TopicId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}

impl FromStr for TopicId {
    type Err = uuid::Error;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Uuid::parse_str(value).map(Self)
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TopicInfo {
    pub name: String,
    /// What the user wants to understand, track, or do.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub description: String,
    #[serde(default)]
    pub metadata: Map<String, Value>,
}

impl TopicInfo {
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            description: String::new(),
            metadata: Map::new(),
        }
    }

    fn validate(&self) -> Result<()> {
        ensure!(!self.name.trim().is_empty(), "A topic needs a name");
        Ok(())
    }
}

pub struct Topics {
    root: PathBuf,
}

impl Topics {
    /// Open or create a catalog in a directory under the host's control.
    pub fn open(root: impl AsRef<Path>) -> Result<Self> {
        let root = root.as_ref();
        let mut builder = fs::DirBuilder::new();
        builder.recursive(true);
        #[cfg(unix)]
        builder.mode(0o700);
        builder.create(root)?;
        Ok(Self {
            root: fs::canonicalize(root)?,
        })
    }

    /// Publish the metadata and the empty file directory together.
    pub fn create(&self, info: TopicInfo) -> Result<Topic> {
        info.validate()?;
        let id = TopicId(Uuid::new_v4());
        let mut builder = Builder::new();
        builder.prefix(".new-");
        #[cfg(unix)]
        builder.permissions(fs::Permissions::from_mode(0o700));
        let staging = builder.tempdir_in(&self.root)?;
        fs::create_dir(staging.path().join("files"))?;
        File::create_new(staging.path().join(LOCK_FILE))?;
        save_info(staging.path(), &info)?;
        let directory = self.root.join(id.to_string());
        fs::rename(staging.path(), &directory)?;
        let _ = staging.keep();
        sync_directory(&self.root)?;
        Ok(Topic { id, directory })
    }

    pub fn get(&self, id: TopicId) -> Result<Topic> {
        let directory = self.root.join(id.to_string());
        ensure!(
            fs::symlink_metadata(&directory)?.is_dir(),
            "Invalid topic directory"
        );
        read_info(&directory)?;
        Ok(Topic { id, directory })
    }

    /// List committed topics in ID order. Return an error for unreadable metadata.
    pub fn list(&self) -> Result<Vec<(TopicId, TopicInfo)>> {
        let mut topics = Vec::new();
        for entry in fs::read_dir(&self.root)? {
            let entry = entry?;
            let name = entry.file_name();
            let Some(name) = name.to_str() else { continue };
            let Ok(id) = name.parse::<TopicId>() else {
                continue;
            };
            if name == id.to_string() && entry.file_type()?.is_dir() {
                topics.push((id, read_info(&entry.path())?));
            }
        }
        topics.sort_unstable_by_key(|(id, _)| *id);
        Ok(topics)
    }
}

#[derive(Clone, Debug)]
pub struct Topic {
    id: TopicId,
    directory: PathBuf,
}

impl Topic {
    pub fn id(&self) -> TopicId {
        self.id
    }

    pub fn info(&self) -> Result<TopicInfo> {
        read_info(&self.directory)
    }

    /// Edit the latest metadata under a per-topic file lock. Return an error from the callback to cancel.
    /// Finish the edit before calling this method again for the same topic.
    pub fn update(&self, edit: impl FnOnce(&mut TopicInfo) -> Result<()>) -> Result<TopicInfo> {
        let lock = File::options()
            .read(true)
            .write(true)
            .open(self.directory.join(LOCK_FILE))?;
        lock.lock()?;
        let mut info = self.info()?;
        edit(&mut info)?;
        info.validate()?;
        save_info(&self.directory, &info)?;
        Ok(info)
    }

    /// Open the directory that contains user files. All relative file operations start here.
    pub fn files(&self) -> Result<Dir> {
        Ok(Dir::open_ambient_dir(
            self.directory.join("files"),
            cap_std::ambient_authority(),
        )?)
    }
}

fn read_info(directory: &Path) -> Result<TopicInfo> {
    let path = directory.join(RECORD_FILE);
    let info: TopicInfo = serde_json::from_slice(&fs::read(&path)?)
        .with_context(|| format!("Cannot read topic metadata in {}", path.display()))?;
    info.validate()?;
    Ok(info)
}

fn save_info(directory: &Path, info: &TopicInfo) -> Result<()> {
    let mut temp = NamedTempFile::new_in(directory)?;
    temp.write_all(&serde_json::to_vec(info)?)?;
    temp.as_file().sync_all()?;
    temp.persist(directory.join(RECORD_FILE))?;
    sync_directory(directory)
}

#[cfg(unix)]
fn sync_directory(directory: &Path) -> Result<()> {
    Ok(File::open(directory)?.sync_all()?)
}

#[cfg(not(unix))]
fn sync_directory(_: &Path) -> Result<()> {
    Ok(())
}
