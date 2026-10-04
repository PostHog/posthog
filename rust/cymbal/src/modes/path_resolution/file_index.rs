use std::collections::HashMap;
use std::hash::{BuildHasher, RandomState};

use super::matching::FileSet;

/// All paths live in one string, and the index keeps offsets into it, so the memory of a list stays
/// close to its text size.
pub struct FileIndex {
    text: Box<str>,
    spans: Box<[(u32, u32)]>,
    // Keyed by a hash of the file name, not the name, so names are not stored twice. A hash
    // collision is harmless because every lookup compares the full paths.
    by_name: HashMap<u64, Vec<u32>>,
    hasher: RandomState,
}

impl FileIndex {
    /// Offsets are u32, so `text` must stay below 4 GiB.
    pub fn from_text(text: String) -> Self {
        let hasher = RandomState::new();
        let mut spans = Vec::new();
        let mut by_name: HashMap<u64, Vec<u32>> = HashMap::new();
        let mut start = 0usize;
        for line in text.split('\n') {
            let end = start + line.len();
            if !line.is_empty() {
                let id = spans.len() as u32;
                spans.push((start as u32, end as u32));
                by_name
                    .entry(hasher.hash_one(file_name(line)))
                    .or_default()
                    .push(id);
            }
            start = end + 1;
        }
        Self {
            text: text.into_boxed_str(),
            spans: spans.into_boxed_slice(),
            by_name,
            hasher,
        }
    }

    pub fn len(&self) -> usize {
        self.spans.len()
    }

    pub fn is_empty(&self) -> bool {
        self.spans.is_empty()
    }

    /// Approximate heap size, used to weigh the entry in the list cache.
    pub fn weight_bytes(&self) -> usize {
        let ids: usize = self.by_name.values().map(Vec::capacity).sum();
        self.text.len()
            + self.spans.len() * std::mem::size_of::<(u32, u32)>()
            + self.by_name.capacity()
                * (std::mem::size_of::<u64>() + std::mem::size_of::<Vec<u32>>())
            + ids * std::mem::size_of::<u32>()
    }

    fn path(&self, id: u32) -> &str {
        let (start, end) = self.spans[id as usize];
        &self.text[start as usize..end as usize]
    }
}

impl FileSet for FileIndex {
    fn files_ending_with<'a>(&'a self, tail: &str) -> Vec<&'a str> {
        let Some(ids) = self.by_name.get(&self.hasher.hash_one(file_name(tail))) else {
            return Vec::new();
        };
        ids.iter()
            .map(|id| self.path(*id))
            .filter(|path| ends_with_segments(path, tail))
            .collect()
    }
}

fn file_name(path: &str) -> &str {
    path.rsplit('/').next().unwrap_or(path)
}

fn ends_with_segments(path: &str, tail: &str) -> bool {
    path == tail
        || (path.len() > tail.len()
            && path.ends_with(tail)
            && path.as_bytes()[path.len() - tail.len() - 1] == b'/')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_files_by_whole_trailing_segments() {
        let index = FileIndex::from_text(
            [
                "apps/web/src/index.tsx",
                "apps/admin/src/index.tsx",
                "src/myindex.tsx",
                "index.tsx",
            ]
            .join("\n"),
        );

        let mut hits = index.files_ending_with("src/index.tsx");
        hits.sort_unstable();
        assert_eq!(
            hits,
            vec!["apps/admin/src/index.tsx", "apps/web/src/index.tsx"]
        );
        assert_eq!(index.files_ending_with("index.tsx").len(), 3);
        assert!(index.files_ending_with("web/src/missing.tsx").is_empty());
        assert_eq!(index.len(), 4);
    }
}
