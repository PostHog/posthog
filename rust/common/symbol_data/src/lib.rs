mod data_types;
mod error;
mod symbol_data;
mod utils;

// Error
pub use error::Error as SymbolDataError;

// The core data type
pub use symbol_data::read_as as read_symbol_data;
pub use symbol_data::write as write_symbol_data;

// Javascript
pub use data_types::sourcemap::SourceAndMap;

// Hermes
pub use data_types::hermesmap::HermesMap;
