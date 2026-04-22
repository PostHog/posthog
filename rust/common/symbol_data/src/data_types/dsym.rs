use crate::symbol_data::{SymbolData, SymbolDataType};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AppleDsym {
    pub data: Vec<u8>,
}

impl SymbolData for AppleDsym {
    fn from_bytes(data: Vec<u8>) -> Result<Self, crate::SymbolDataError> {
        Ok(Self { data })
    }

    fn into_bytes(self) -> Vec<u8> {
        self.data
    }

    fn data_type() -> crate::symbol_data::SymbolDataType {
        SymbolDataType::AppleDsym
    }
}
