//! Native orchestration. JavaScript is only entered for synchronous, pure
//! custom transforms; effects are always delegated to a view-scoped host.
use super::{Condition, DataOperation, Join, Step, Workflow};
use crate::{FailureKind, HostError};
use serde_json::{Value, json};
use std::{
    cell::{Cell, RefCell},
    collections::{BTreeMap, HashMap},
    future::{Future, poll_fn},
    pin::Pin,
    rc::Rc,
    task::Poll,
    time::Instant,
};

pub type Result<T> = std::result::Result<T, String>;
pub type LocalFuture<'a, T> = Pin<Box<dyn Future<Output = T> + 'a>>;

pub trait Host {
    fn now_ms(&self) -> i64 {
        chrono::Utc::now().timestamp_millis()
    }
    fn current(&self) -> bool {
        true
    }
    fn expression(
        &self,
        code: String,
        input: Value,
    ) -> LocalFuture<'_, Result<super::expressions::Evaluation>> {
        Box::pin(async move { super::expressions::evaluate(&code, input, None) })
    }
    fn state(&self) -> Result<Value>;
    fn patch(&self, value: Value) -> Result<()>;
    fn data(&self, op: &str, table: &str, args: Value) -> Result<Value>;
    fn transform(&self, name: &str, args: Value) -> Result<Value>;
    fn request(
        &self,
        method: &str,
        params: Value,
    ) -> LocalFuture<'_, std::result::Result<Value, HostError>>;
    /// A snapshot of the run so far, at most a few times a second, for
    /// showing progress live. Hosts that can't show it ignore it.
    fn progress(&self, _workflow: &str, _trace: &Value) {}
}

/// Closing the channel wakes every pending branch, including host requests.
#[derive(Clone)]
pub struct Control {
    tx: async_channel::Sender<()>,
    pub cancelled: async_channel::Receiver<()>,
}
impl Default for Control {
    fn default() -> Self {
        let (tx, cancelled) = async_channel::bounded(1);
        Self { tx, cancelled }
    }
}
impl Control {
    pub fn cancel(&self) {
        self.tx.close();
    }
    pub fn check(&self) -> Result<()> {
        if self.tx.is_closed() {
            Err("Workflow cancelled".into())
        } else {
            Ok(())
        }
    }
}

#[derive(Clone, Default)]
struct Scope {
    input: Rc<Value>,
    outputs: HashMap<String, Rc<Value>>,
    item: Option<Rc<Value>>,
    index: Option<Value>,
    error: Option<Value>,
    run: Rc<Value>,
}

#[derive(Default, serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct NodeTrace {
    started: usize,
    completed: usize,
    failed: usize,
    recovered: usize,
    skipped: usize,
    elapsed_ms: u64,
    /// When the step first started, from the start of the run.
    #[serde(skip_serializing_if = "Option::is_none")]
    start_ms: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    evaluation_us: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

pub struct Run {
    pub result: Result<Value>,
    pub trace: Value,
}
/// Carries the innermost failing step across branch joins and try/catch.
struct StepError {
    diagnostic: HostError,
    steps: Vec<String>,
}
type StepResult<T> = std::result::Result<T, StepError>;
impl From<HostError> for StepError {
    fn from(diagnostic: HostError) -> Self {
        Self {
            diagnostic,
            steps: vec![],
        }
    }
}
impl From<String> for StepError {
    fn from(message: String) -> Self {
        HostError::from(message).into()
    }
}
impl From<&str> for StepError {
    fn from(message: &str) -> Self {
        message.to_owned().into()
    }
}
impl StepError {
    fn message(&self) -> String {
        let mut message = String::new();
        for step in self.steps.iter().rev() {
            message.push_str(&format!("Step {step}: "));
        }
        message.push_str(&self.diagnostic.message);
        message
    }
    fn at_step(mut self, step: &Step) -> Self {
        if self.steps.is_empty() {
            match step {
                Step::Source { source, .. } => {
                    self.diagnostic.source.get_or_insert_with(|| source.clone());
                }
                Step::Cli { .. } | Step::Ai { .. } | Step::Agent { .. } | Step::Notify { .. } => {}
                _ => {
                    self.diagnostic.kind.get_or_insert(FailureKind::Logic);
                }
            }
        }
        self.steps.push(step.id().into());
        self
    }
}
struct Runner<'a> {
    host: &'a dyn Host,
    control: Control,
    permits: tokio::sync::Semaphore,
    trace: RefCell<BTreeMap<String, NodeTrace>>,
    produced: Cell<usize>,
    operations: Cell<usize>,
    workflow: String,
    started: Instant,
    reported: Cell<Option<Instant>>,
}

/// How often a running workflow reports its progress.
const PROGRESS_EVERY: std::time::Duration = std::time::Duration::from_millis(250);

pub async fn run(host: &dyn Host, workflow: &Workflow, input: Value, control: Control) -> Run {
    let runner = Runner {
        host,
        control,
        permits: tokio::sync::Semaphore::new(workflow.concurrency),
        trace: RefCell::default(),
        produced: Cell::new(0),
        operations: Cell::new(0),
        workflow: workflow.id.clone(),
        started: Instant::now(),
        reported: Cell::new(None),
    };
    let started = runner.started;
    let now = host.now_ms();
    let mut scope = Scope {
        input: Rc::new(input),
        run: Rc::new(
            json!({"nowMs":now,"startedAt":chrono::DateTime::from_timestamp_millis(now).unwrap_or_default().to_rfc3339_opts(chrono::SecondsFormat::Millis,true)}),
        ),
        ..Default::default()
    };
    let result: StepResult<Value> = if workflow.version != 2 {
        Err("Native execution requires workflow version 2".into())
    } else {
        runner
            .steps(&workflow.steps, &mut scope)
            .await
            .and_then(|()| {
                if let Some(result) = &workflow.result {
                    Ok(runner.resolve(result, &scope)?)
                } else {
                    Ok(scope
                        .outputs
                        .into_iter()
                        .map(|(key, value)| (key, (*value).clone()))
                        .collect())
                }
            })
    };
    let mut trace = json!({"engine":"rust","elapsedMs":started.elapsed().as_millis() as u64,"nodes":*runner.trace.borrow()});
    if let Err(error) = &result {
        trace["failure"] = json!({"step":error.steps.first(),"diagnostic":error.diagnostic});
    }
    Run {
        trace,
        result: result.map_err(|error| error.message()),
    }
}

// Poll every branch on the same thread as its host engine. Settling all branches
// before returning prevents an error racing a sibling's state/dataset writes.
async fn settle_all<T>(mut tasks: Vec<LocalFuture<'_, T>>) -> Vec<T> {
    let mut output: Vec<Option<T>> = (0..tasks.len()).map(|_| None).collect();
    poll_fn(|cx| {
        let mut pending = false;
        for (i, task) in tasks.iter_mut().enumerate() {
            if output[i].is_none() {
                match task.as_mut().poll(cx) {
                    Poll::Ready(value) => output[i] = Some(value),
                    Poll::Pending => pending = true,
                }
            }
        }
        if pending {
            Poll::Pending
        } else {
            Poll::Ready(())
        }
    })
    .await;
    output.into_iter().map(Option::unwrap).collect()
}

impl Runner<'_> {
    fn resolve(&self, value: &Value, scope: &Scope) -> Result<Value> {
        match value {
            Value::Array(items) => items.iter().map(|v| self.resolve(v, scope)).collect(),
            Value::Object(object) if object.contains_key("$ref") => {
                let reference = object["$ref"].as_str().ok_or("Reference must be text")?;
                let (root, rest) = reference[1..]
                    .split_once('/')
                    .unwrap_or((&reference[1..], ""));
                let pointer = if rest.is_empty() && !reference.ends_with('/') {
                    String::new()
                } else {
                    format!("/{rest}")
                };
                let mut state;
                let found = match root {
                    "input" => scope.input.pointer(&pointer),
                    "state" => {
                        state = self.host.state()?;
                        state.pointer(&pointer)
                    }
                    "item" => scope.item.as_deref().and_then(|v| v.pointer(&pointer)),
                    "index" => scope.index.as_ref().and_then(|v| v.pointer(&pointer)),
                    "error" => scope.error.as_ref().and_then(|v| v.pointer(&pointer)),
                    "run" => {
                        state = (*scope.run).clone();
                        state["current"] = json!(self.host.current());
                        state.pointer(&pointer)
                    }
                    "steps" => {
                        let (id, tail) = rest.split_once('/').unwrap_or((rest, ""));
                        let id = id.replace("~1", "/").replace("~0", "~");
                        if rest.is_empty() {
                            return Ok(scope
                                .outputs
                                .iter()
                                .map(|(k, v)| (k.clone(), (**v).clone()))
                                .collect());
                        }
                        let tail = if tail.is_empty() && !reference.ends_with('/') {
                            String::new()
                        } else {
                            format!("/{tail}")
                        };
                        scope.outputs.get(&id).and_then(|v| v.pointer(&tail))
                    }
                    _ => None,
                };
                found.cloned().map(Ok).unwrap_or_else(|| {
                    object
                        .get("default")
                        .map(|v| self.resolve(v, scope))
                        .unwrap_or_else(|| Err(format!("Missing reference {reference}")))
                })
            }
            Value::Object(object) => object
                .iter()
                .map(|(k, v)| Ok((k.clone(), self.resolve(v, scope)?)))
                .collect(),
            _ => Ok(value.clone()),
        }
    }
    fn condition(&self, c: &Condition, s: &Scope) -> Result<bool> {
        use Condition::*;
        Ok(match c {
            All { conditions } => {
                for c in conditions {
                    if !self.condition(c, s)? {
                        return Ok(false);
                    }
                }
                true
            }
            Any { conditions } => {
                for c in conditions {
                    if self.condition(c, s)? {
                        return Ok(true);
                    }
                }
                false
            }
            Not { condition } => !self.condition(condition, s)?,
            Truthy { value } => match self.resolve(value, s)? {
                Value::Null => false,
                Value::Bool(v) => v,
                Value::Number(v) => v.as_f64() != Some(0.),
                Value::String(v) => !v.is_empty(),
                _ => true,
            },
            Eq { left, right } => self.resolve(left, s)? == self.resolve(right, s)?,
            Ne { left, right } => self.resolve(left, s)? != self.resolve(right, s)?,
            Gt { left, right } | Gte { left, right } | Lt { left, right } | Lte { left, right } => {
                let l = self
                    .resolve(left, s)?
                    .as_f64()
                    .ok_or("Numeric comparison needs two numbers")?;
                let r = self
                    .resolve(right, s)?
                    .as_f64()
                    .ok_or("Numeric comparison needs two numbers")?;
                match c {
                    Gt { .. } => l > r,
                    Gte { .. } => l >= r,
                    Lt { .. } => l < r,
                    _ => l <= r,
                }
            }
        })
    }
    fn effect_input(&self, value: &Value, scope: &Scope) -> StepResult<Value> {
        self.resolve(value, scope)
            .map_err(|error| HostError::classified(FailureKind::Logic, error).into())
    }

    async fn effect(&self, method: &str, params: Value) -> StepResult<Value> {
        self.control.check()?;
        tokio::select! {
            biased;
            _ = self.control.cancelled.recv() => Err("Workflow cancelled".into()),
            result = async {
                let _permit = self.permits.acquire().await.map_err(|e| e.to_string())?;
                self.control.check()?;
                Ok(self.host.request(method,params).await?)
            } => { self.control.check()?; result }
        }
    }
    /// Sends the run so far to the host, no more often than PROGRESS_EVERY.
    fn report(&self, force: bool) {
        let now = Instant::now();
        if !force
            && self
                .reported
                .get()
                .is_some_and(|last| now.duration_since(last) < PROGRESS_EVERY)
        {
            return;
        }
        self.reported.set(Some(now));
        let trace = json!({
            "engine": "rust",
            "live": true,
            "elapsedMs": self.started.elapsed().as_millis() as u64,
            "nodes": *self.trace.borrow(),
        });
        self.host.progress(&self.workflow, &trace);
    }
    fn steps<'a>(
        &'a self,
        steps: &'a [Step],
        scope: &'a mut Scope,
    ) -> LocalFuture<'a, StepResult<()>> {
        Box::pin(async move {
            for step in steps {
                self.control.check()?;
                self.operations.set(self.operations.get() + 1);
                if self.operations.get() > 20_000 {
                    return Err("Workflow exceeded 20000 step executions".into());
                }
                let started = Instant::now();
                {
                    let mut traces = self.trace.borrow_mut();
                    let trace = traces.entry(step.id().into()).or_default();
                    trace.started += 1;
                    trace
                        .start_ms
                        .get_or_insert(self.started.elapsed().as_millis() as u64);
                }
                self.report(false);
                let write = matches!(
                    step,
                    Step::State { .. }
                        | Step::Dataset {
                            operation: DataOperation::Set
                                | DataOperation::Patch
                                | DataOperation::Remove
                                | DataOperation::Clear,
                            ..
                        }
                );
                // A worker may finish an expression after a newer generation
                // started. Check freshness at the synchronous commit boundary.
                if write && !self.host.current() {
                    self.trace.borrow_mut().get_mut(step.id()).unwrap().skipped += 1;
                    scope.outputs.insert(step.id().into(), Rc::new(Value::Null));
                    continue;
                }
                let result = self.step(step, scope).await.and_then(|value| {
                    self.control.check()?;
                    // Bound intermediate results, including custom transform outputs.
                    let bytes = serde_json::to_vec(&value).map_err(|e| e.to_string())?.len();
                    self.produced.set(self.produced.get().saturating_add(bytes));
                    if bytes > 8 * 1024 * 1024 || self.produced.get() > 64 * 1024 * 1024 {
                        return Err(
                            "Workflow results exceed the native execution memory budget".into()
                        );
                    }
                    Ok(value)
                });
                {
                    let mut traces = self.trace.borrow_mut();
                    let trace = traces.get_mut(step.id()).unwrap();
                    trace.elapsed_ms = trace
                        .elapsed_ms
                        .saturating_add(started.elapsed().as_millis() as u64);
                    match &result {
                        Ok(_) => trace.completed += 1,
                        Err(error) => {
                            trace.failed += 1;
                            trace.error = Some(error.message().chars().take(512).collect());
                        }
                    }
                }
                self.report(false);
                scope.outputs.insert(
                    step.id().into(),
                    Rc::new(result.map_err(|e| e.at_step(step))?),
                );
            }
            Ok(())
        })
    }
    fn step<'a>(&'a self, step: &'a Step, s: &'a mut Scope) -> LocalFuture<'a, StepResult<Value>> {
        Box::pin(async move {
            Ok(match step {
                Step::Source {
                    source,
                    source_by_name,
                    tool,
                    arguments,
                    ..
                } => {
                    self.effect(
                        "sources.call",
                        json!({"source":source,"source_by_name":source_by_name,"tool":tool,"arguments":self.effect_input(arguments,s)?}),
                    )
                    .await?
                }
                Step::Cli {
                    permit,
                    cli_reference,
                    args,
                    options,
                    ..
                } => {
                    let options = self.effect_input(options, s)?;
                    let mut params = json!({"id":permit,"args":self.effect_input(args,s)?});
                    if let Some(reference) = cli_reference {
                        params["cli_reference"] = json!(reference);
                    }
                    if let Some(timeout) = options.get("timeoutMs") {
                        params["timeout_ms"] = timeout.clone();
                    }
                    if let Some(pattern) = options.get("pattern") {
                        params["pattern"] = pattern.clone();
                    }
                    self.effect("cli.run", params).await?
                }
                Step::Ai { options, .. } => {
                    self.effect("native.ai.run", self.effect_input(options, s)?)
                        .await?
                }
                Step::Agent { options, .. } => {
                    self.effect("native.agents.execute", self.effect_input(options, s)?)
                        .await?
                }
                Step::Notify { options, .. } => {
                    self.effect("native.notifications.send", self.effect_input(options, s)?)
                        .await?
                }
                Step::State { patch, .. } => {
                    let patch = self.resolve(patch, s)?;
                    if !patch.is_object() {
                        return Err("State patch must be an object".into());
                    }
                    if patch
                        .as_object()
                        .unwrap()
                        .keys()
                        .any(|k| ["__proto__", "constructor", "prototype"].contains(&k.as_str()))
                    {
                        return Err("Reserved workflow state key".into());
                    }
                    self.host.patch(patch.clone())?;
                    patch
                }
                Step::Dataset {
                    table,
                    operation,
                    value,
                    options,
                    ..
                } => {
                    let value = self.resolve(value, s)?;
                    let (op, args) = match operation {
                        DataOperation::Set => (
                            "set",
                            json!({"rows":value,"options":self.resolve(options,s)?}),
                        ),
                        DataOperation::Patch => (
                            "patch",
                            json!({"rows":value,"options":self.resolve(options,s)?}),
                        ),
                        DataOperation::Remove => ("remove", json!({"keys":value})),
                        DataOperation::Clear => ("clear", json!({})),
                        DataOperation::Rows => ("rows", value),
                        DataOperation::Count => ("count", value),
                        DataOperation::Aggregate => ("aggregate", value),
                    };
                    self.host.data(op, table, args)?
                }
                Step::Command { command, args, .. } => {
                    self.host.transform(command, self.resolve(args, s)?)?
                }
                Step::Expression {
                    id, code, input, ..
                } => {
                    let input = self.resolve(input, s)?;
                    let _permit = self.permits.acquire().await.map_err(|e| e.to_string())?;
                    self.control.check()?;
                    let evaluated = self.host.expression(code.clone(), input).await?;
                    self.control.check()?;
                    let mut trace = self.trace.borrow_mut();
                    let node = trace.entry(id.clone()).or_default();
                    node.evaluation_us = Some(
                        node.evaluation_us
                            .unwrap_or(0)
                            .saturating_add(evaluated.elapsed_us),
                    );
                    evaluated.value
                }
                Step::If {
                    condition,
                    then,
                    otherwise,
                    ..
                } => {
                    let yes = self.condition(condition, s)?;
                    self.steps(if yes { then } else { otherwise }, s).await?;
                    json!(yes)
                }
                Step::Parallel { branches, .. } => {
                    let tasks = branches
                        .iter()
                        .map(|branch| {
                            let mut local = s.clone();
                            Box::pin(async move {
                                self.steps(&branch.steps, &mut local).await?;
                                Ok((branch.id.clone(), self.resolve(&branch.result, &local)?))
                            })
                                as LocalFuture<'_, StepResult<(String, Value)>>
                        })
                        .collect();
                    settle_all(tasks)
                        .await
                        .into_iter()
                        .collect::<StepResult<serde_json::Map<_, _>>>()?
                        .into()
                }
                Step::Map {
                    items,
                    concurrency,
                    limit,
                    steps,
                    result,
                    ..
                } => {
                    let items = self.resolve(items, s)?;
                    let items = items.as_array().ok_or("Map items must be an array")?;
                    if items.len() > *limit {
                        return Err(
                            format!("Map has {} items; limit is {limit}", items.len()).into()
                        );
                    }
                    let next = Cell::new(0usize);
                    let failed = Cell::new(false);
                    let output = RefCell::new(vec![Value::Null; items.len()]);
                    let tasks = (0..(*concurrency).min(items.len()))
                        .map(|_| {
                            let parent = s.clone();
                            let (next, failed, output) = (&next, &failed, &output);
                            Box::pin(async move {
                                while !failed.get() {
                                    let i = next.get();
                                    if i >= items.len() {
                                        break;
                                    }
                                    next.set(i + 1);
                                    let mut local = parent.clone();
                                    local.item = Some(Rc::new(items[i].clone()));
                                    local.index = Some(json!(i));
                                    let value = match self
                                        .steps(steps, &mut local)
                                        .await
                                        .and_then(|()| Ok(self.resolve(result, &local)?))
                                    {
                                        Ok(value) => value,
                                        Err(error) => {
                                            failed.set(true);
                                            return Err(error);
                                        }
                                    };
                                    output.borrow_mut()[i] = value;
                                }
                                Ok(())
                            }) as LocalFuture<'_, StepResult<()>>
                        })
                        .collect();
                    for done in settle_all(tasks).await {
                        done?;
                    }
                    output.into_inner().into()
                }
                Step::Merge { base, joins, .. } => self.merge(self.resolve(base, s)?, joins, s)?,
                Step::Try {
                    id,
                    steps,
                    result,
                    fallback,
                    catch,
                    rethrow,
                    ..
                } => {
                    let mut local = s.clone();
                    match self
                        .steps(steps, &mut local)
                        .await
                        .and_then(|()| Ok(self.resolve(result, &local)?))
                    {
                        Ok(value) => value,
                        Err(error) => {
                            self.control.check()?;
                            local.error = Some(json!({"message":error.message()}));
                            self.steps(catch, &mut local).await?;
                            if *rethrow {
                                return Err(error);
                            }
                            self.trace
                                .borrow_mut()
                                .entry(id.clone())
                                .or_default()
                                .recovered += 1;
                            self.resolve(fallback, &local)?
                        }
                    }
                }
            })
        })
    }
    fn merge(&self, base: Value, joins: &[Join], scope: &Scope) -> Result<Value> {
        let mut rows = base
            .as_array()
            .ok_or("Merge base must be an array")?
            .clone();
        if rows.iter().any(|r| !r.is_object()) {
            return Err("Merge rows must be objects".into());
        }
        for join in joins {
            let source = self.resolve(&join.from, scope)?;
            let source = source.as_array().ok_or("Merge source must be an array")?;
            let mut index: HashMap<String, Vec<&Value>> = HashMap::new();
            let mut weights: HashMap<String, usize> = HashMap::new();
            for row in source {
                if let Some(key) = join_key(row.pointer(&join.right_key))? {
                    *weights.entry(key.clone()).or_default() +=
                        serde_json::to_vec(row).map_err(|e| e.to_string())?.len();
                    let matches = index.entry(key).or_default();
                    if !join.many && !matches.is_empty() {
                        return Err(format!(
                            "Merge source has duplicate keys for {}",
                            join.field
                        ));
                    }
                    matches.push(row);
                }
            }
            let mut produced = 0usize;
            for row in &mut rows {
                self.control.check()?;
                let key = join_key(row.pointer(&join.left_key))?;
                produced = produced
                    .saturating_add(serde_json::to_vec(row).map_err(|e| e.to_string())?.len())
                    .saturating_add(join.field.len())
                    .saturating_add(
                        key.as_ref()
                            .and_then(|k| weights.get(k))
                            .copied()
                            .unwrap_or(0),
                    );
                if produced > 8 * 1024 * 1024 {
                    return Err(
                        "Merge output exceeds 8 MB; filter inputs or split into batches".into(),
                    );
                }
                let matches = key.as_ref().and_then(|k| index.get(k));
                let value = if join.many {
                    Value::Array(
                        matches
                            .into_iter()
                            .flatten()
                            .map(|v| (*v).clone())
                            .collect(),
                    )
                } else {
                    matches
                        .and_then(|v| v.first())
                        .map(|v| (*v).clone())
                        .unwrap_or(Value::Null)
                };
                row.as_object_mut()
                    .unwrap()
                    .insert(join.field.clone(), value);
            }
        }
        Ok(rows.into())
    }
}
fn join_key(value: Option<&Value>) -> Result<Option<String>> {
    match value {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Array(_) | Value::Object(_)) => {
            Err("Merge keys must be strings, numbers or booleans".into())
        }
        Some(value) => Ok(Some(value.to_string())),
    }
}
