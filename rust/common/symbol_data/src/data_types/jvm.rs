use std::collections::BTreeMap;

use crate::{
    error::Error,
    symbol_data::{SymbolData, SymbolDataType},
    utils::assert_at_least_as_long_as,
};

/// Symbols for one JVM build: an optional ProGuard/R8 mapping and the build's source files.
///
/// `sources` maps a lookup key to the text of one source file. The key is the file's package
/// path joined with its file name (`com/acme/Foo.kt`), because a JVM stack frame carries only the
/// class name and the source file name, not the path of the file in the repository.
///
/// The encoding is deterministic: the same mapping and sources always give the same bytes. The
/// CLI derives the symbol set id from these bytes, so that the same build never gets two ids.
// Each source entry needs memory for its map node and string headers, also when its key and
// contents are empty. The reader rejects a larger count before it builds the map, so that a small
// bundle cannot make the reader allocate much more memory than the bundle size suggests. The limit
// also keeps that overhead small next to a symbol cache budget, so that a cache can hold a bundle of
// many empty files instead of evicting it and parsing it again for each frame. One application has
// far fewer source files.
pub const MAX_JVM_BUNDLE_SOURCES: usize = 100_000;

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct JvmBundle {
    pub mapping: Option<String>,
    pub sources: BTreeMap<String, String>,
}

struct Reader<'a> {
    data: &'a [u8],
    offset: usize,
}

impl<'a> Reader<'a> {
    fn take(&mut self, len: usize) -> Result<&'a [u8], Error> {
        let end = self
            .offset
            .checked_add(len)
            .ok_or(Error::DataTooShort(u64::MAX, self.data.len() as u64))?;
        assert_at_least_as_long_as(end, self.data.len())?;
        let bytes = &self.data[self.offset..end];
        self.offset = end;
        Ok(bytes)
    }

    fn u64(&mut self) -> Result<u64, Error> {
        Ok(u64::from_le_bytes(self.take(8)?.try_into().unwrap()))
    }

    fn string(&mut self) -> Result<String, Error> {
        let len = self.u64()?;
        let len = usize::try_from(len).map_err(|_| Error::DataTooShort(len, 0))?;
        Ok(String::from_utf8(self.take(len)?.to_vec())?)
    }
}

fn push_string(buffer: &mut Vec<u8>, value: &str) {
    buffer.extend_from_slice(&(value.len() as u64).to_le_bytes());
    buffer.extend_from_slice(value.as_bytes());
}

impl SymbolData for JvmBundle {
    fn from_bytes(data: Vec<u8>) -> Result<Self, Error> {
        let mut reader = Reader {
            data: &data,
            offset: 0,
        };

        let mapping = match reader.take(1)?[0] {
            0 => None,
            _ => Some(reader.string()?),
        };

        let count = reader.u64()?;
        if count > MAX_JVM_BUNDLE_SOURCES as u64 {
            return Err(Error::TooManyEntries(count, MAX_JVM_BUNDLE_SOURCES as u64));
        }
        let mut sources = BTreeMap::new();
        for _ in 0..count {
            let key = reader.string()?;
            let content = reader.string()?;
            sources.insert(key, content);
        }

        if reader.offset != data.len() {
            return Err(Error::DataTooLong(data.len() as u64, reader.offset as u64));
        }

        Ok(Self { mapping, sources })
    }

    fn into_bytes(self) -> Vec<u8> {
        let mut buffer = Vec::new();
        match &self.mapping {
            Some(mapping) => {
                buffer.push(1);
                push_string(&mut buffer, mapping);
            }
            None => buffer.push(0),
        }
        buffer.extend_from_slice(&(self.sources.len() as u64).to_le_bytes());
        for (key, content) in &self.sources {
            push_string(&mut buffer, key);
            push_string(&mut buffer, content);
        }
        buffer
    }

    fn data_type() -> SymbolDataType {
        SymbolDataType::JvmBundle
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_bundle_over_the_source_limit_is_rejected_before_its_entries_are_read() {
        let count = MAX_JVM_BUNDLE_SOURCES as u64 + 1;
        let mut data = vec![0];
        data.extend_from_slice(&count.to_le_bytes());

        assert_eq!(
            JvmBundle::from_bytes(data),
            Err(Error::TooManyEntries(count, MAX_JVM_BUNDLE_SOURCES as u64))
        );
    }
}
