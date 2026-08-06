//! Error taxonomy surfaced to the caller in v1. The shared wire enum lives in
//! cymbal-proto so client and server classify failures without parsing strings.

pub use cymbal_proto::cymbal::resolution::v1::ErrorKind;
