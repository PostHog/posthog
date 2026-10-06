/// The request fields that apply to every message of one request on the
/// wire, so a request never mixes classes.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct RequestClass {
    pub assignment_epoch: u64,
    /// The request repeats messages that a worker may already have seen.
    pub replay: bool,
}
