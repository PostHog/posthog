use tokio::sync::oneshot;

use crate::error::Error;

use super::frames::{Frame, RawFrame};

pub struct Stack<S>(S);

// The basic idea is that we want to be able to get a bunch of stacks, explode them into
// their individual frames, and then cluster and resolve those frames however we want, and
// once we've kicked off all those tasks or whatever, we just can use the stack object itself
// to wait for the results to come back. This is /kind of/ a future, but with more flexibility.
// The win here is that we're able to process a batch of events all at once, but we pay some
// complexity cost.
pub struct FrameResolveWaiter {
    handle: oneshot::Receiver<Result<Frame, Error>>,
}

pub struct FrameResolveHandle {
    frame: RawFrame,
    handle: oneshot::Sender<Result<Frame, Error>>,
}

// The state transitions a stack can go through, from a stack of unprocessed frames, to an intermediate
// state where the stack has been "exploded" and is waiting on the results of each frame, to a stack of
// resolved frames.
pub struct Unprocessed(Vec<RawFrame>);
pub struct Resolving(Vec<FrameResolveWaiter>);
pub struct Resolved(Vec<Frame>);

pub struct FrameBag(Vec<FrameResolveHandle>);

pub type UnprocessedStack = Stack<Unprocessed>;
pub type ResolvingStack = Stack<Resolving>;
pub type ResolvedStack = Stack<Resolved>;

impl From<Vec<RawFrame>> for Stack<Unprocessed> {
    fn from(frames: Vec<RawFrame>) -> Self {
        Self(Unprocessed(frames))
    }
}

impl Stack<Unprocessed> {
    pub fn explode(self) -> (Stack<Resolving>, FrameBag) {
        let mut waiters = Vec::with_capacity(self.0 .0.len());
        let mut handles = Vec::with_capacity(self.0 .0.len());
        for frame in self.0 .0.into_iter() {
            let (tx, rx) = oneshot::channel();
            waiters.push(FrameResolveWaiter { handle: rx });
            handles.push(FrameResolveHandle { frame, handle: tx });
        }

        (Stack(Resolving(waiters)), FrameBag(handles))
    }
}

impl FrameBag {
    pub fn merge(self, other: Self) -> Self {
        let mut handles = self.0;
        handles.extend(other.0);
        FrameBag(handles)
    }

    pub async fn resolve(self) {
        // Things get a little tricky with indexes here...
        let mut frames = Vec::with_capacity(self.0.len());
        let mut handles = Vec::with_capacity(self.0.len());
        for (i, handle) in self.0.into_iter().enumerate() {
            frames.push(handle.frame);
            handles.push(handle.handle);
        }

        Ok(Stack(Resolved(frames)))
    }
}

struct FrameGroup<Ref, Frame> {
    source_ref: Option<Ref>,
    frames: Vec<Frame>,
    indices: Vec<usize>,
}
