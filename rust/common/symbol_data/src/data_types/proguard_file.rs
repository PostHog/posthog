use crate::symbol_data::{SymbolData, SymbolDataType};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProguardFile {
    pub content: String,
}

impl SymbolData for ProguardFile {
    fn from_bytes(data: Vec<u8>) -> Result<Self, crate::SymbolDataError> {
        Ok(Self {
            content: String::from_utf8(data)?,
        })
    }

    fn into_bytes(self) -> Vec<u8> {
        self.content.into_bytes()
    }

    fn data_type() -> crate::symbol_data::SymbolDataType {
        SymbolDataType::ProguardFile
    }
}
