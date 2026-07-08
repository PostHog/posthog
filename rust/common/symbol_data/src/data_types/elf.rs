use crate::symbol_data::{SymbolData, SymbolDataType};

/// Debug information for a native ELF binary, packaged as a ZIP with the
/// DWARF-bearing binary stored as `dwarf` at the root plus an optional
/// `__source/` bundle — the same layout as `AppleDsym`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ElfDebugInfo {
    pub data: Vec<u8>,
}

impl SymbolData for ElfDebugInfo {
    fn from_bytes(data: Vec<u8>) -> Result<Self, crate::SymbolDataError> {
        Ok(Self { data })
    }

    fn into_bytes(self) -> Vec<u8> {
        self.data
    }

    fn data_type() -> SymbolDataType {
        SymbolDataType::ElfDebugInfo
    }
}
