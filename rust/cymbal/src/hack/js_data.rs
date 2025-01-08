use serde::{Deserialize, Serialize};
use symbolic::sourcemapcache::{SourceMapCache, SourceMapCacheWriter};
use thiserror::Error;

use crate::symbol_store::sourcemap::OwnedSourceMapCache;

// NOTE: see posthog/api/error_tracking.py
pub struct JsData {
    data: Vec<u8>,
    // For legacy reasons, before we has this serialisation format,
    // we wrote raw SourceMapCache data to s3. This flag is set if
    // the wrapped data here is in that format
    is_raw_smc: bool,
}

#[derive(Debug)]
enum JsDataType {
    SourceAndMap = 2,
    SourceMapCache = 3,
}

#[derive(Debug, Error, Serialize, Deserialize)]
pub enum JsDataError {
    #[error("invalid source map cache: {0}")]
    InvalidSourceMapCache(String),
    #[error("Wrong version: {0}")]
    WrongVersion(u32),
    #[error("Data too short, at index {0}")]
    DataTooShort(u64),
    #[error("Data too long, at index {0}")]
    DataTooLong(u64),
    #[error("Invalid magic")]
    InvalidMagic,
    #[error("Invalid data type: {0}")]
    InvalidDataType(u32),
    #[error("Invalid data type {0} for operation {1}")]
    InvalidDataTypeForOperation(u32, String),
    #[error("Invalid utf8, got error: {0}")]
    InvalidUtf8(String),
}

impl JsData {
    const MAGIC: &'static [u8] = b"posthog_error_tracking";
    const VERSION: u32 = 1;

    pub fn from_source_and_map(s: String, sm: String) -> Self {
        let mut data = Vec::with_capacity(s.len() + sm.len() + 128);
        Self::add_header(&mut data, JsDataType::SourceAndMap);
        data.extend_from_slice(&(s.len() as u64).to_le_bytes());
        data.extend_from_slice(s.as_bytes());
        drop(s);
        data.extend_from_slice(&(sm.len() as u64).to_le_bytes());
        data.extend_from_slice(sm.as_bytes());
        drop(sm);
        Self {
            data,
            is_raw_smc: false,
        }
    }

    // TODO - this path has no coverage, because its never called. We should add coverage, or remove it
    // entirely, once we decide whether we ever want to store SMC data rather than the original minified
    // source and map
    pub fn from_smc(smc: SourceMapCacheWriter, len_hint: usize) -> Result<Self, JsDataError> {
        let mut data = Vec::with_capacity(len_hint);
        Self::add_header(&mut data, JsDataType::SourceMapCache);

        let len_before = data.len();
        // Reserve space for the length of the SMC
        data.extend_from_slice(&0u64.to_le_bytes());

        smc.serialize(&mut data)
            .map_err(|e| JsDataError::InvalidSourceMapCache(e.to_string()))?;

        let len_after = data.len();
        let smc_len = (len_after - len_before) as u64;
        data[len_before..len_before + 8].copy_from_slice(&smc_len.to_le_bytes());
        Ok(Self {
            data,
            is_raw_smc: false,
        })
    }

    pub fn from_bytes(data: Vec<u8>) -> Result<Self, JsDataError> {
        let maybe = Self {
            data,
            is_raw_smc: false,
        };

        if let Err(e) = maybe.assert_has_header() {
            return maybe.try_be_a_raw_source_map_cache().ok_or(e);
        }
        if let Err(e) = maybe.assert_has_magic() {
            return maybe.try_be_a_raw_source_map_cache().ok_or(e);
        }

        let version = maybe.get_version();
        if version > Self::VERSION {
            return Err(JsDataError::WrongVersion(version));
        }

        let data_type = maybe.get_data_type()?;

        match data_type {
            JsDataType::SourceAndMap => {
                maybe.assert_has_source_and_map()?;
            }
            JsDataType::SourceMapCache => {
                maybe.assert_has_source_map_cache()?;
            }
        }

        Ok(maybe)
    }

    pub fn to_bytes(self) -> Vec<u8> {
        self.data
    }

    pub fn to_smc(self) -> Result<OwnedSourceMapCache, JsDataError> {
        if self.is_raw_smc {
            // UNWRAP: safe as flag is only set by try_be_a_raw_source_map_cache, which
            // asserts this parse succeeds
            return Ok(OwnedSourceMapCache::new(self.data).unwrap());
        }

        match self.get_data_type()? {
            JsDataType::SourceAndMap => {
                let source = std::str::from_utf8(self.get_minified_source()?)
                    .map_err(|e| JsDataError::InvalidUtf8(e.to_string()))?;
                let map = std::str::from_utf8(self.get_sourcemap()?)
                    .map_err(|e| JsDataError::InvalidUtf8(e.to_string()))?;
                OwnedSourceMapCache::from_source_and_map(source, map)
                    .map_err(|e| JsDataError::InvalidSourceMapCache(e.to_string()))
            }
            JsDataType::SourceMapCache => {
                OwnedSourceMapCache::new(self.data[Self::header_len() + 8..].to_vec())
                    .map_err(|e| JsDataError::InvalidSourceMapCache(e.to_string()))
            }
        }
    }

    fn add_header(data: &mut Vec<u8>, data_type: JsDataType) {
        data.extend_from_slice(Self::MAGIC);
        data.extend_from_slice(&Self::VERSION.to_le_bytes());
        data.extend_from_slice(&(data_type as u32).to_le_bytes());
    }

    fn assert_has_header(&self) -> Result<(), JsDataError> {
        if self.data.len() < Self::header_len() {
            return Err(JsDataError::DataTooShort(0));
        }
        Ok(())
    }

    fn assert_has_magic(&self) -> Result<(), JsDataError> {
        if &self.data[..Self::MAGIC.len()] != Self::MAGIC {
            return Err(JsDataError::InvalidMagic);
        }
        Ok(())
    }

    fn get_version(&self) -> u32 {
        u32::from_le_bytes(
            self.data[Self::MAGIC.len()..Self::MAGIC.len() + 4]
                .try_into()
                .unwrap(),
        )
    }

    fn get_data_type(&self) -> Result<JsDataType, JsDataError> {
        let data_type = u32::from_le_bytes(
            self.data[Self::header_len() - 4..Self::header_len()]
                .try_into()
                .unwrap(),
        );
        JsDataType::try_from(data_type)
    }

    fn assert_has_source_and_map(&self) -> Result<(), JsDataError> {
        let s_len = u64::from_le_bytes(
            self.data[Self::header_len()..Self::header_len() + 8]
                .try_into()
                .unwrap(),
        );

        let sm_len = u64::from_le_bytes(
            self.data[Self::header_len() + 8 + s_len as usize
                ..Self::header_len() + 8 + s_len as usize + 8]
                .try_into()
                .unwrap(),
        );

        let expected_length = Self::header_len() + 16 + s_len as usize + sm_len as usize;

        if self.data.len() < expected_length {
            return Err(JsDataError::DataTooShort(expected_length as u64));
        }

        if self.data.len() > expected_length {
            return Err(JsDataError::DataTooLong(expected_length as u64));
        }
        Ok(())
    }

    fn assert_has_source_map_cache(&self) -> Result<(), JsDataError> {
        let smc_len = u64::from_le_bytes(
            self.data[Self::header_len()..Self::header_len() + 8]
                .try_into()
                .unwrap(),
        );

        let expected_length = Self::header_len() + 8 + smc_len as usize;

        if self.data.len() < expected_length {
            return Err(JsDataError::DataTooShort(expected_length as u64));
        }

        if self.data.len() > expected_length {
            return Err(JsDataError::DataTooLong(expected_length as u64));
        }
        Ok(())
    }

    fn get_minified_source(&self) -> Result<&[u8], JsDataError> {
        if !matches!(self.get_data_type()?, JsDataType::SourceAndMap) {
            return Err(JsDataError::InvalidDataTypeForOperation(
                self.get_data_type()? as u32,
                "get_minified_source".to_string(),
            ));
        }
        let s_len = u64::from_le_bytes(
            self.data[Self::header_len()..Self::header_len() + 8]
                .try_into()
                .unwrap(),
        );

        Ok(&self.data[Self::header_len() + 8..Self::header_len() + 8 + s_len as usize])
    }

    fn get_sourcemap(&self) -> Result<&[u8], JsDataError> {
        if !matches!(self.get_data_type()?, JsDataType::SourceAndMap) {
            return Err(JsDataError::InvalidDataTypeForOperation(
                self.get_data_type()? as u32,
                "get_sourcemap".to_string(),
            ));
        }

        let s_len = self.get_minified_source()?.len();
        let sm_len = u64::from_le_bytes(
            self.data[Self::header_len() + 8 + s_len..Self::header_len() + 8 + s_len + 8]
                .try_into()
                .unwrap(),
        );
        Ok(&self.data[Self::header_len() + 8 + s_len + 8
            ..Self::header_len() + 8 + s_len + 8 + sm_len as usize])
    }

    fn try_be_a_raw_source_map_cache(mut self) -> Option<Self> {
        let test = SourceMapCache::parse(&self.data).is_ok();
        if test {
            self.is_raw_smc = true;
            return Some(self);
        }
        None
    }

    const fn header_len() -> usize {
        Self::MAGIC.len() + Self::VERSION.to_le_bytes().len() + std::mem::size_of::<u32>()
    }
}

impl TryFrom<u32> for JsDataType {
    type Error = JsDataError;

    fn try_from(value: u32) -> Result<Self, Self::Error> {
        match value {
            2 => Ok(JsDataType::SourceAndMap),
            3 => Ok(JsDataType::SourceMapCache),
            _ => Err(JsDataError::InvalidDataType(value)),
        }
    }
}
