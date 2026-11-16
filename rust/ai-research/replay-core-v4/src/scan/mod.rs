//! One linear byte pass over a recording. Nothing builds a JSON tree: the scanner locates spans, and only the few
//! values a caller asks for are decoded.

pub mod canvas;
pub mod cv;
pub mod images;
pub mod message;
pub mod tokens;
