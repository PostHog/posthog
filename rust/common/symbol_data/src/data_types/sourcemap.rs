use crate::{
    error::Error,
    symbol_data::{SymbolData, SymbolDataType},
    utils::assert_at_least_as_long_as,
};

// NOTE: see posthog/api/error_tracking.py
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceAndMap {
    pub minified_source: String,
    pub sourcemap: String,
}

impl SymbolData for SourceAndMap {
    fn from_bytes(data: Vec<u8>) -> Result<Self, Error> {
        assert_at_least_as_long_as(8, data.len())?;
        let s_len = u64::from_le_bytes(data[0..8].try_into().unwrap()) as usize;

        assert_at_least_as_long_as(s_len + 8, data.len())?;
        let minified_source = String::from_utf8(data[8..8 + s_len].to_vec())?;

        assert_at_least_as_long_as(8 + s_len + 8, data.len())?;
        let sm_len =
            u64::from_le_bytes(data[8 + s_len..8 + s_len + 8].try_into().unwrap()) as usize;

        assert_at_least_as_long_as(sm_len + 8 + s_len + 8, data.len())?;
        let sourcemap = String::from_utf8(data[8 + s_len + 8..8 + s_len + 8 + sm_len].to_vec())?;

        if 8 + s_len + 8 + sm_len != data.len() {
            return Err(Error::DataTooLong(
                data.len() as u64,
                (8 + s_len + 8 + sm_len) as u64,
            ));
        }
        Ok(Self {
            minified_source,
            sourcemap,
        })
    }

    fn into_bytes(self) -> Vec<u8> {
        let mut data = Vec::with_capacity(self.minified_source.len() + self.sourcemap.len() + 16);
        data.extend_from_slice(&self.minified_source.len().to_le_bytes());
        data.extend_from_slice(self.minified_source.as_bytes());
        data.extend_from_slice(&self.sourcemap.len().to_le_bytes());
        data.extend_from_slice(self.sourcemap.as_bytes());
        data
    }

    fn data_type() -> crate::symbol_data::SymbolDataType {
        SymbolDataType::SourceAndMap
    }
}
