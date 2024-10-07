use crate::symbols::types::RawStack;

// An "exception" is anything that can self-identify with a "fingerprint"
pub trait Exception {
    fn id(&self) -> String;
    fn to_raw(self) -> serde_json::Value;
}

// Some excpetions have a raw stack trace we can process. If they do,

pub trait Stacked: Exception {
    fn stack(&self) -> RawStack;
}
