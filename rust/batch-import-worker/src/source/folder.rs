use std::path::PathBuf;

use anyhow::Error;
use async_trait::async_trait;
use tokio::io::{AsyncReadExt, AsyncSeekExt};

use super::DataSource;

pub struct FolderSource {
    pub path: PathBuf,
}

impl FolderSource {
    pub async fn new(path: String) -> Result<Self, Error> {
        let path = tokio::fs::canonicalize(path).await?;
        Ok(Self { path })
    }

    pub async fn assert_valid_path(&self, key: &str) -> Result<(), Error> {
        if !self.keys().await?.into_iter().any(|k| k == key) {
            return Err(Error::msg(format!("Key not found: {key}")));
        }
        Ok(())
    }
}

#[async_trait]
impl DataSource for FolderSource {
    async fn keys(&self) -> Result<Vec<String>, Error> {
        let mut keys = vec![];
        let mut entries = tokio::fs::read_dir(&self.path).await?;
        while let Some(entry) = entries.next_entry().await? {
            keys.push(entry.file_name().to_string_lossy().to_string());
        }
        Ok(keys)
    }

    async fn size(&self, key: &str) -> Result<Option<u64>, Error> {
        self.assert_valid_path(key).await?;
        let path = self.path.join(key);
        let metadata = tokio::fs::metadata(path).await?;
        Ok(Some(metadata.len()))
    }

    async fn get_chunk(&self, key: &str, offset: u64, size: u64) -> Result<Vec<u8>, Error> {
        self.assert_valid_path(key).await?;
        let path = self.path.join(key);
        let mut file = tokio::fs::File::open(path).await?;
        file.seek(std::io::SeekFrom::Start(offset)).await?;
        // Read until either we reach `size` bytes or the end of the file
        let mut res = Vec::with_capacity(size as usize);
        let mut buffer = vec![0; 1024];
        while (res.len() as u64) < size {
            let bytes_read = file.read(&mut buffer).await?;
            if bytes_read == 0 {
                break;
            }
            res.extend_from_slice(&buffer[..bytes_read]);
        }

        // The last call to read might have read more than `size` bytes, so truncate the result
        if (res.len() as u64) > size {
            res.truncate(size as usize);
        }
        Ok(res)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    async fn setup_test_folder() -> (TempDir, FolderSource) {
        let temp_dir = TempDir::new().unwrap();
        fs::write(temp_dir.path().join("test1.txt"), b"hello world").unwrap();
        fs::write(temp_dir.path().join("test2.txt"), b"another file").unwrap();

        let source = FolderSource::new(temp_dir.path().to_str().unwrap().to_string())
            .await
            .unwrap();

        (temp_dir, source)
    }

    #[tokio::test]
    async fn test_keys() {
        let (_temp_dir, source) = setup_test_folder().await;
        let keys = source.keys().await.unwrap();
        assert_eq!(keys.len(), 2);
        assert!(keys.contains(&"test1.txt".to_string()));
        assert!(keys.contains(&"test2.txt".to_string()));
    }

    #[tokio::test]
    async fn test_size() {
        let (_temp_dir, source) = setup_test_folder().await;
        let size = source.size("test1.txt").await.unwrap();
        assert_eq!(size, Some(11));
    }

    #[tokio::test]
    async fn test_get_chunk() {
        let (_temp_dir, source) = setup_test_folder().await;
        let chunk = source.get_chunk("test1.txt", 0, 5).await.unwrap();
        assert_eq!(chunk, b"hello");
    }

    #[tokio::test]
    async fn test_invalid_path() {
        let (_temp_dir, source) = setup_test_folder().await;
        let result = source.assert_valid_path("nonexistent.txt").await;
        assert!(result.is_err());
    }
}
