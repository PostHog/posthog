use crate::symbol_data::{SymbolData, SymbolDataType};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HermesMap {
    pub sourcemap: String, // JSON content of sourcemap
}

impl SymbolData for HermesMap {
    fn from_bytes(data: Vec<u8>) -> Result<Self, crate::SymbolDataError> {
        Ok(Self {
            sourcemap: String::from_utf8(data)?,
        })
    }

    fn into_bytes(self) -> Vec<u8> {
        self.sourcemap.into_bytes()
    }

    fn data_type() -> crate::symbol_data::SymbolDataType {
        SymbolDataType::HermesMap
    }
}
