//! Canonical names for the database pools, used as the `pool` label on metrics.
//!
//! These are constants because a wrong label fails nothing. The code compiles, the query
//! runs, and the metric is emitted under a second time series whose name differs from the
//! intended one by a character or a word, while the original series keeps reporting as if
//! that traffic had stopped. Nobody sees an error, so the first sign of trouble is a
//! dashboard that disagrees with the database. Referring to a constant turns that into a
//! compile error.

pub const PERSONS_READER: &str = "persons_reader";
pub const PERSONS_WRITER: &str = "persons_writer";
pub const NON_PERSONS_READER: &str = "non_persons_reader";
pub const NON_PERSONS_WRITER: &str = "non_persons_writer";
