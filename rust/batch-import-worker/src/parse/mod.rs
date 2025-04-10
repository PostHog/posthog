pub mod content;
pub mod format;

pub struct Parsed<T> {
    pub data: T,
    // How many "parts" of the chunk (bytes, rows) were consumed to create the data. This allows for offset
    // storing etc in an input-format-aware-manner
    pub consumed: usize,
}
