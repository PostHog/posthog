//! Step traits, the typed builder, and the per-chunk executor.
//!
//! Authors write two kinds of steps:
//! - [`Step`] — a synchronous, per-event step (the workhorse). Consecutive
//!   sync steps run fused, one event at a time, within a single pass.
//! - [`ChunkStep`] — an asynchronous, whole-chunk step (batched Redis lookups,
//!   Kafka produce acks). It closes the current sync segment and forms an async
//!   stage boundary.
//!
//! The [`PipelineBuilder`] threads the current event type as a generic
//! parameter, so composition is checked at compile time: `.step()` only accepts
//! a step whose input matches the type the previous step produced. Internally
//! the executor stores steps type-erased (`Box<dyn Any + Send>`) so a segment is
//! a homogeneous `Vec` it can iterate while recording which step decided each
//! verdict. See `POC_NOTES.md` for why this differs from the design's fully
//! monomorphized `Chain`.

use std::any::Any;
use std::marker::PhantomData;

use async_trait::async_trait;

use crate::result::{Outputs, StepError, StepResult};

/// A synchronous per-event step. `Fx` is the pipeline's composed effects struct;
/// steps constrain it with capability bounds (see [`crate::plugin`]).
pub trait Step<In, Fx>: Send + Sync {
    /// The (possibly type-changed) event state produced on `Continue`.
    type Out;
    /// The pipeline's redirect-target enum.
    type Outputs: Outputs;

    /// Apply the step to one event, returning its verdict.
    fn apply(
        &self,
        event: In,
        fx: &mut Fx,
    ) -> Result<StepResult<Self::Out, Self::Outputs>, StepError>;

    /// Stable step name for stack traces and the `last_step_name` metric label.
    fn name(&self) -> &'static str;
}

/// An asynchronous chunk-scoped step. Receives the events that survived the
/// preceding sync segment and must return exactly one verdict per input, in
/// order.
#[async_trait]
pub trait ChunkStep<In, Fx>: Send + Sync {
    /// The (possibly type-changed) event state produced on `Continue`.
    type Out;
    /// The pipeline's redirect-target enum.
    type Outputs: Outputs;

    /// Apply the step to the whole chunk. The returned vec must be the same
    /// length as `events`, with verdicts recorded positionally.
    async fn apply_chunk(
        &self,
        events: Vec<In>,
        fx: &mut Fx,
    ) -> Result<Vec<StepResult<Self::Out, Self::Outputs>>, StepError>;

    /// Stable step name for stack traces and metric labels.
    fn name(&self) -> &'static str;
}

/// The kind of a terminal verdict, used as the `result` metric label.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VerdictKind {
    Drop,
    Dlq,
    Redirect,
}

impl VerdictKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            VerdictKind::Drop => "drop",
            VerdictKind::Dlq => "dlq",
            VerdictKind::Redirect => "redirect",
        }
    }
}

/// A recorded terminal verdict for one event, tagged with the deciding step.
pub struct Verdict<O: Outputs> {
    pub kind: VerdictKind,
    /// Metric `details` label. For redirects this is the output's name.
    pub reason: &'static str,
    /// Name of the step that produced this verdict (`last_step_name`).
    pub step: &'static str,
    /// Present only for `Redirect` verdicts.
    pub output: Option<O>,
    /// Whether the original Kafka key is preserved (`Redirect` only).
    pub preserve_key: bool,
    /// Optional diagnostic error (`Dlq` only); not produced downstream.
    pub error: Option<anyhow::Error>,
}

impl<O: Outputs> std::fmt::Debug for Verdict<O> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Verdict")
            .field("kind", &self.kind)
            .field("reason", &self.reason)
            .field("step", &self.step)
            .field("output", &self.output)
            .field("preserve_key", &self.preserve_key)
            .field("error", &self.error.as_ref().map(|e| e.to_string()))
            .finish()
    }
}

/// The outcome for a single input event after the whole pipeline runs.
#[derive(Debug)]
pub enum ItemOutcome<Out, O: Outputs> {
    /// The event survived every stage, carrying its final state.
    Survived(Out),
    /// The event hit a terminal verdict at some step.
    Terminated(Verdict<O>),
}

impl<Out, O: Outputs> ItemOutcome<Out, O> {
    pub fn is_survivor(&self) -> bool {
        matches!(self, ItemOutcome::Survived(_))
    }
}

/// The result of running one chunk: one [`ItemOutcome`] per input, same order
/// and length as the input.
#[derive(Debug)]
pub struct ChunkOutcome<Out, O: Outputs> {
    pub items: Vec<ItemOutcome<Out, O>>,
}

impl<Out, O: Outputs> ChunkOutcome<Out, O> {
    /// Consume the outcome, returning just the survivors (order preserved).
    pub fn into_survivors(self) -> Vec<Out> {
        self.items
            .into_iter()
            .filter_map(|item| match item {
                ItemOutcome::Survived(out) => Some(out),
                ItemOutcome::Terminated(_) => None,
            })
            .collect()
    }

    /// Number of survivors.
    pub fn survivor_count(&self) -> usize {
        self.items.iter().filter(|i| i.is_survivor()).count()
    }
}

// --- internal type-erased machinery ---

type AnyBox = Box<dyn Any + Send>;

/// A terminal verdict before the deciding step name is attached.
struct PartialVerdict<O: Outputs> {
    kind: VerdictKind,
    reason: &'static str,
    output: Option<O>,
    preserve_key: bool,
    error: Option<anyhow::Error>,
}

impl<O: Outputs> PartialVerdict<O> {
    fn into_verdict(self, step: &'static str) -> Verdict<O> {
        Verdict {
            kind: self.kind,
            reason: self.reason,
            step,
            output: self.output,
            preserve_key: self.preserve_key,
            error: self.error,
        }
    }
}

enum ErasedOutcome<O: Outputs> {
    Continue(AnyBox),
    Terminal(PartialVerdict<O>),
}

fn to_erased<T: Send + 'static, O: Outputs>(result: StepResult<T, O>) -> ErasedOutcome<O> {
    match result {
        StepResult::Continue(out) => {
            let boxed: AnyBox = Box::new(out);
            ErasedOutcome::Continue(boxed)
        }
        StepResult::Drop { reason } => ErasedOutcome::Terminal(PartialVerdict {
            kind: VerdictKind::Drop,
            reason,
            output: None,
            preserve_key: false,
            error: None,
        }),
        StepResult::Dlq { reason, error } => ErasedOutcome::Terminal(PartialVerdict {
            kind: VerdictKind::Dlq,
            reason,
            output: None,
            preserve_key: false,
            error,
        }),
        StepResult::Redirect {
            output,
            preserve_key,
        } => ErasedOutcome::Terminal(PartialVerdict {
            kind: VerdictKind::Redirect,
            reason: output.name(),
            output: Some(output),
            preserve_key,
            error: None,
        }),
    }
}

trait ErasedStep<Fx, O: Outputs>: Send + Sync {
    fn apply_erased(&self, event: AnyBox, fx: &mut Fx) -> Result<ErasedOutcome<O>, StepError>;
    fn name(&self) -> &'static str;
}

struct StepBox<S, In> {
    step: S,
    _in: PhantomData<fn(In)>,
}

impl<S, In, Fx, O> ErasedStep<Fx, O> for StepBox<S, In>
where
    S: Step<In, Fx, Outputs = O> + 'static,
    In: Send + 'static,
    S::Out: Send + 'static,
    Fx: 'static,
    O: Outputs,
{
    fn apply_erased(&self, event: AnyBox, fx: &mut Fx) -> Result<ErasedOutcome<O>, StepError> {
        let input: Box<In> = event.downcast().unwrap_or_else(|_| {
            panic!(
                "pipeline type mismatch entering step '{}': input was not the expected type",
                self.step.name()
            )
        });
        Ok(to_erased(self.step.apply(*input, fx)?))
    }

    fn name(&self) -> &'static str {
        self.step.name()
    }
}

#[async_trait]
trait ErasedChunkStep<Fx, O: Outputs>: Send + Sync {
    async fn apply_chunk_erased(
        &self,
        events: Vec<AnyBox>,
        fx: &mut Fx,
    ) -> Result<Vec<ErasedOutcome<O>>, StepError>;
    fn name(&self) -> &'static str;
}

struct ChunkStepBox<S, In> {
    step: S,
    _in: PhantomData<fn(In)>,
}

#[async_trait]
impl<S, In, Fx, O> ErasedChunkStep<Fx, O> for ChunkStepBox<S, In>
where
    S: ChunkStep<In, Fx, Outputs = O> + 'static,
    In: Send + 'static,
    S::Out: Send + 'static,
    Fx: Send + 'static,
    O: Outputs,
{
    async fn apply_chunk_erased(
        &self,
        events: Vec<AnyBox>,
        fx: &mut Fx,
    ) -> Result<Vec<ErasedOutcome<O>>, StepError> {
        let n = events.len();
        let inputs: Vec<In> = events
            .into_iter()
            .map(|e| {
                *e.downcast::<In>().unwrap_or_else(|_| {
                    panic!(
                        "pipeline type mismatch entering chunk step '{}'",
                        self.step.name()
                    )
                })
            })
            .collect();
        let results = self.step.apply_chunk(inputs, fx).await?;
        if results.len() != n {
            return Err(StepError::msg(format!(
                "chunk step '{}' returned {} results for {} inputs (must match)",
                self.step.name(),
                results.len(),
                n
            )));
        }
        Ok(results.into_iter().map(to_erased).collect())
    }

    fn name(&self) -> &'static str {
        self.step.name()
    }
}

enum Stage<Fx, O: Outputs> {
    Sync(Vec<Box<dyn ErasedStep<Fx, O>>>),
    Chunk(Box<dyn ErasedChunkStep<Fx, O>>),
}

/// A built pipeline: an ordered list of stages. Run it over a chunk with
/// [`Pipeline::run_chunk`].
pub struct Pipeline<In, Out, Fx, O: Outputs> {
    stages: Vec<Stage<Fx, O>>,
    _marker: PhantomData<fn(In) -> Out>,
}

enum SlotState<O: Outputs> {
    Alive(AnyBox),
    Done(Verdict<O>),
}

impl<In, Out, Fx, O> Pipeline<In, Out, Fx, O>
where
    In: Send + 'static,
    Out: Send + 'static,
    Fx: Send + 'static,
    O: Outputs,
{
    /// Start building a pipeline whose first stage consumes `In`.
    pub fn builder() -> PipelineBuilder<In, In, Fx, O> {
        PipelineBuilder::new()
    }

    /// Run the pipeline over one chunk of events. Returns one outcome per input,
    /// in the same order. An `Err` is the unexpected-error channel: it should
    /// poison the batch (consumer profile) rather than be treated per-event.
    pub async fn run_chunk(
        &self,
        items: Vec<In>,
        fx: &mut Fx,
    ) -> Result<ChunkOutcome<Out, O>, StepError> {
        let mut slots: Vec<Option<SlotState<O>>> = items
            .into_iter()
            .map(|item| {
                let boxed: AnyBox = Box::new(item);
                Some(SlotState::Alive(boxed))
            })
            .collect();

        for stage in &self.stages {
            match stage {
                Stage::Sync(steps) => {
                    for slot in slots.iter_mut() {
                        let current = match slot.take().expect("slot present") {
                            SlotState::Done(v) => {
                                *slot = Some(SlotState::Done(v));
                                continue;
                            }
                            SlotState::Alive(b) => b,
                        };
                        let final_state = 'steps: {
                            let mut value = current;
                            for step in steps {
                                match step.apply_erased(value, fx)? {
                                    ErasedOutcome::Continue(next) => value = next,
                                    ErasedOutcome::Terminal(pv) => {
                                        break 'steps SlotState::Done(pv.into_verdict(step.name()))
                                    }
                                }
                            }
                            SlotState::Alive(value)
                        };
                        *slot = Some(final_state);
                    }
                }
                Stage::Chunk(chunk_step) => {
                    let mut indices = Vec::new();
                    let mut inputs = Vec::new();
                    for (i, slot) in slots.iter_mut().enumerate() {
                        match slot.take().expect("slot present") {
                            SlotState::Alive(b) => {
                                indices.push(i);
                                inputs.push(b);
                            }
                            SlotState::Done(v) => *slot = Some(SlotState::Done(v)),
                        }
                    }
                    if inputs.is_empty() {
                        continue;
                    }
                    let results = chunk_step.apply_chunk_erased(inputs, fx).await?;
                    for (idx, outcome) in indices.into_iter().zip(results) {
                        let state = match outcome {
                            ErasedOutcome::Continue(b) => SlotState::Alive(b),
                            ErasedOutcome::Terminal(pv) => {
                                SlotState::Done(pv.into_verdict(chunk_step.name()))
                            }
                        };
                        slots[idx] = Some(state);
                    }
                }
            }
        }

        let items = slots
            .into_iter()
            .map(|slot| match slot.expect("slot present") {
                SlotState::Alive(b) => {
                    let out: Box<Out> = b.downcast().unwrap_or_else(|_| {
                        panic!("pipeline output type mismatch: survivor was not the expected type")
                    });
                    ItemOutcome::Survived(*out)
                }
                SlotState::Done(v) => ItemOutcome::Terminated(v),
            })
            .collect();

        Ok(ChunkOutcome { items })
    }
}

/// Typed builder. `In` is the pipeline's input type; `Cur` is the type the next
/// step must consume (it advances as steps are added).
pub struct PipelineBuilder<In, Cur, Fx, O: Outputs> {
    stages: Vec<Stage<Fx, O>>,
    open_sync: Vec<Box<dyn ErasedStep<Fx, O>>>,
    _marker: PhantomData<fn(In) -> Cur>,
}

impl<In, Fx, O> PipelineBuilder<In, In, Fx, O>
where
    Fx: Send + 'static,
    O: Outputs,
{
    /// Create an empty builder. Prefer [`Pipeline::builder`].
    pub fn new() -> Self {
        PipelineBuilder {
            stages: Vec::new(),
            open_sync: Vec::new(),
            _marker: PhantomData,
        }
    }
}

impl<In, Fx, O> Default for PipelineBuilder<In, In, Fx, O>
where
    Fx: Send + 'static,
    O: Outputs,
{
    fn default() -> Self {
        Self::new()
    }
}

impl<In, Cur, Fx, O> PipelineBuilder<In, Cur, Fx, O>
where
    Cur: Send + 'static,
    Fx: Send + 'static,
    O: Outputs,
{
    /// Append a synchronous step to the current sync segment.
    pub fn step<S>(mut self, step: S) -> PipelineBuilder<In, S::Out, Fx, O>
    where
        S: Step<Cur, Fx, Outputs = O> + 'static,
        S::Out: Send + 'static,
    {
        self.open_sync.push(Box::new(StepBox {
            step,
            _in: PhantomData::<fn(Cur)>,
        }));
        PipelineBuilder {
            stages: self.stages,
            open_sync: self.open_sync,
            _marker: PhantomData,
        }
    }

    /// Close the current sync segment and append an async chunk stage.
    pub fn chunk_step<S>(mut self, step: S) -> PipelineBuilder<In, S::Out, Fx, O>
    where
        S: ChunkStep<Cur, Fx, Outputs = O> + 'static,
        S::Out: Send + 'static,
    {
        if !self.open_sync.is_empty() {
            self.stages
                .push(Stage::Sync(std::mem::take(&mut self.open_sync)));
        }
        self.stages.push(Stage::Chunk(Box::new(ChunkStepBox {
            step,
            _in: PhantomData::<fn(Cur)>,
        })));
        PipelineBuilder {
            stages: self.stages,
            open_sync: Vec::new(),
            _marker: PhantomData,
        }
    }

    /// Finish building. Flushes any open sync segment.
    pub fn build(mut self) -> Pipeline<In, Cur, Fx, O> {
        if !self.open_sync.is_empty() {
            self.stages
                .push(Stage::Sync(std::mem::take(&mut self.open_sync)));
        }
        Pipeline {
            stages: self.stages,
            _marker: PhantomData,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::result::Outputs;

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    enum TestOut {
        Overflow,
    }
    impl Outputs for TestOut {
        fn name(&self) -> &'static str {
            match self {
                TestOut::Overflow => "overflow",
            }
        }
    }

    // Drops zero, else continues (i32 -> i32).
    struct ParseSign;
    impl Step<i32, ()> for ParseSign {
        type Out = i32;
        type Outputs = TestOut;
        fn apply(&self, event: i32, _fx: &mut ()) -> Result<StepResult<i32, TestOut>, StepError> {
            if event == 0 {
                Ok(StepResult::drop("zero"))
            } else {
                Ok(StepResult::Continue(event))
            }
        }
        fn name(&self) -> &'static str {
            "parse_sign"
        }
    }

    // Redirects negatives to overflow (preserving key), else continues.
    struct Redirector;
    impl Step<i32, ()> for Redirector {
        type Out = i32;
        type Outputs = TestOut;
        fn apply(&self, event: i32, _fx: &mut ()) -> Result<StepResult<i32, TestOut>, StepError> {
            if event < 0 {
                Ok(StepResult::redirect(TestOut::Overflow, true))
            } else {
                Ok(StepResult::Continue(event))
            }
        }
        fn name(&self) -> &'static str {
            "redirector"
        }
    }

    // DLQs values > 100, else continues.
    struct Dlqer;
    impl Step<i32, ()> for Dlqer {
        type Out = i32;
        type Outputs = TestOut;
        fn apply(&self, event: i32, _fx: &mut ()) -> Result<StepResult<i32, TestOut>, StepError> {
            if event > 100 {
                Ok(StepResult::dlq("too_big"))
            } else {
                Ok(StepResult::Continue(event))
            }
        }
        fn name(&self) -> &'static str {
            "dlqer"
        }
    }

    // Type-changing: i32 -> String.
    struct Stringify;
    impl Step<i32, ()> for Stringify {
        type Out = String;
        type Outputs = TestOut;
        fn apply(
            &self,
            event: i32,
            _fx: &mut (),
        ) -> Result<StepResult<String, TestOut>, StepError> {
            Ok(StepResult::Continue(event.to_string()))
        }
        fn name(&self) -> &'static str {
            "stringify"
        }
    }

    #[tokio::test]
    async fn verdicts_are_positional_and_step_tagged() {
        let pipeline = Pipeline::<i32, String, (), TestOut>::builder()
            .step(ParseSign)
            .step(Redirector)
            .step(Dlqer)
            .step(Stringify)
            .build();

        let mut fx = ();
        let outcome = pipeline
            .run_chunk(vec![0, -5, 200, 42], &mut fx)
            .await
            .unwrap();

        assert_eq!(outcome.items.len(), 4);

        match &outcome.items[0] {
            ItemOutcome::Terminated(v) => {
                assert_eq!(v.kind, VerdictKind::Drop);
                assert_eq!(v.reason, "zero");
                assert_eq!(v.step, "parse_sign");
            }
            _ => panic!("expected drop"),
        }
        match &outcome.items[1] {
            ItemOutcome::Terminated(v) => {
                assert_eq!(v.kind, VerdictKind::Redirect);
                assert_eq!(v.step, "redirector");
                assert_eq!(v.output, Some(TestOut::Overflow));
                assert!(v.preserve_key);
            }
            _ => panic!("expected redirect"),
        }
        match &outcome.items[2] {
            ItemOutcome::Terminated(v) => {
                assert_eq!(v.kind, VerdictKind::Dlq);
                assert_eq!(v.reason, "too_big");
                assert_eq!(v.step, "dlqer");
            }
            _ => panic!("expected dlq"),
        }
        match &outcome.items[3] {
            ItemOutcome::Survived(s) => assert_eq!(s, "42"),
            _ => panic!("expected survivor"),
        }
    }

    #[tokio::test]
    async fn survivors_helper_preserves_order() {
        let pipeline = Pipeline::<i32, i32, (), TestOut>::builder()
            .step(ParseSign)
            .build();
        let mut fx = ();
        let outcome = pipeline
            .run_chunk(vec![1, 0, 2, 0, 3], &mut fx)
            .await
            .unwrap();
        assert_eq!(outcome.survivor_count(), 3);
        assert_eq!(outcome.into_survivors(), vec![1, 2, 3]);
    }

    // --- chunk-step boundary tests ---

    struct RejectBad;
    impl Step<String, ()> for RejectBad {
        type Out = String;
        type Outputs = TestOut;
        fn apply(
            &self,
            event: String,
            _fx: &mut (),
        ) -> Result<StepResult<String, TestOut>, StepError> {
            if event == "bad" {
                Ok(StepResult::drop("bad_sync"))
            } else {
                Ok(StepResult::Continue(event))
            }
        }
        fn name(&self) -> &'static str {
            "reject_bad"
        }
    }

    struct ShoutChunk;
    #[async_trait]
    impl ChunkStep<String, ()> for ShoutChunk {
        type Out = String;
        type Outputs = TestOut;
        async fn apply_chunk(
            &self,
            events: Vec<String>,
            _fx: &mut (),
        ) -> Result<Vec<StepResult<String, TestOut>>, StepError> {
            Ok(events
                .into_iter()
                .map(|e| {
                    if e == "drop" {
                        StepResult::drop("drop_chunk")
                    } else {
                        StepResult::Continue(format!("{e}!"))
                    }
                })
                .collect())
        }
        fn name(&self) -> &'static str {
            "shout_chunk"
        }
    }

    #[tokio::test]
    async fn chunk_boundary_excludes_sync_dropped_and_preserves_order() {
        let pipeline = Pipeline::<String, String, (), TestOut>::builder()
            .step(RejectBad)
            .chunk_step(ShoutChunk)
            .build();

        let mut fx = ();
        let input = vec![
            "hi".to_string(),
            "bad".to_string(),
            "drop".to_string(),
            "ok".to_string(),
        ];
        let outcome = pipeline.run_chunk(input, &mut fx).await.unwrap();

        match &outcome.items[0] {
            ItemOutcome::Survived(s) => assert_eq!(s, "hi!"),
            _ => panic!("expected survivor hi!"),
        }
        match &outcome.items[1] {
            ItemOutcome::Terminated(v) => {
                assert_eq!(v.reason, "bad_sync");
                assert_eq!(v.step, "reject_bad");
            }
            _ => panic!("expected bad_sync drop"),
        }
        match &outcome.items[2] {
            ItemOutcome::Terminated(v) => {
                assert_eq!(v.reason, "drop_chunk");
                assert_eq!(v.step, "shout_chunk");
            }
            _ => panic!("expected drop_chunk"),
        }
        match &outcome.items[3] {
            ItemOutcome::Survived(s) => assert_eq!(s, "ok!"),
            _ => panic!("expected survivor ok!"),
        }
    }

    struct WrongLengthChunk;
    #[async_trait]
    impl ChunkStep<String, ()> for WrongLengthChunk {
        type Out = String;
        type Outputs = TestOut;
        async fn apply_chunk(
            &self,
            _events: Vec<String>,
            _fx: &mut (),
        ) -> Result<Vec<StepResult<String, TestOut>>, StepError> {
            // Deliberately returns too few results.
            Ok(vec![StepResult::Continue("only_one".to_string())])
        }
        fn name(&self) -> &'static str {
            "wrong_length"
        }
    }

    #[derive(Debug, thiserror::Error, PartialEq)]
    #[error("batch structurally invalid")]
    struct GateError;

    // Rejects the whole chunk when any item is negative (gate semantics).
    struct RejectingGate;
    impl Step<i32, ()> for RejectingGate {
        type Out = i32;
        type Outputs = TestOut;
        fn apply(&self, event: i32, _fx: &mut ()) -> Result<StepResult<i32, TestOut>, StepError> {
            if event < 0 {
                Err(StepError::reject(GateError))
            } else {
                Ok(StepResult::Continue(event))
            }
        }
        fn name(&self) -> &'static str {
            "rejecting_gate"
        }
    }

    #[tokio::test]
    async fn reject_aborts_chunk_and_surfaces_typed_error() {
        let pipeline = Pipeline::<i32, i32, (), TestOut>::builder()
            .step(RejectingGate)
            .build();
        let mut fx = ();
        let err = pipeline
            .run_chunk(vec![1, -2, 3], &mut fx)
            .await
            .unwrap_err();
        let recovered: GateError = err.try_into_reject().expect("typed reject");
        assert_eq!(recovered, GateError);
    }

    #[tokio::test]
    async fn chunk_step_length_mismatch_is_error() {
        let pipeline = Pipeline::<String, String, (), TestOut>::builder()
            .chunk_step(WrongLengthChunk)
            .build();
        let mut fx = ();
        let err = pipeline
            .run_chunk(vec!["a".to_string(), "b".to_string()], &mut fx)
            .await
            .unwrap_err();
        assert!(err.to_string().contains("must match"));
    }
}
