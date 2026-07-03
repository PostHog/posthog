use std::any::Any;
use std::cell::RefCell;
use std::rc::Rc;

use indexmap::IndexMap;
use serde::de::DeserializeOwned;
use serde_json::{json, Value as JsonValue};

use crate::{
    context::{ExecutionContext, Symbol},
    error::VmError,
    memory::{HeapReference, VmHeap},
    ops::Operation,
    state::{
        chunk_str, chunk_to_symbol, close_over_cells, closure_from_json, closure_to_json,
        collect_cells, rebuild_cells, root_closure_json, value_from_json, value_to_json,
        CallFrameJson, CellRegistry, Resumable, ThrowFrameJson, UpvalueJson, VmSnapshot,
    },
    util::{get_json_nested, like, regex_match},
    values::{
        compare_values, Callable, Closure, FromHogLiteral, HogLiteral, HogValue, LocalCallable,
        Num, NumOp, Upvalue, UpvalueCell,
    },
};

pub const MAX_JSON_SERDE_DEPTH: usize = 64;

/// The outcome of a virtual machine step.
#[derive(Debug, Clone)]
pub enum StepOutcome {
    /// The program has completed, returning a value
    Finished(JsonValue),
    /// The program has requested a global function call. The driver dispatches it: a registered
    /// native (STL/ext) runs inline; a registered *async* function (see [`ExecutionContext::is_async`])
    /// suspends the resumable driver instead — at this point the args are already popped and `ip` is
    /// past the call, so a snapshot taken now resumes correctly once the result is pushed.
    NativeCall(String, Vec<HogValue>),
    /// The program has requested another step
    Continue,
}

/// Some debug information about a virtual machine failure, returned by some
/// helpers when a VM step returns an error
#[derive(Debug, Clone)]
pub struct VmFailure {
    pub error: VmError,
    pub ip: usize,
    pub stack: Vec<HogValue>, // TODO - only used for debugging, should remove
    pub step: usize,
}

/// The Hog Virtual Machine. Represents the state of a running program.
pub struct HogVM<'a> {
    /// The heap of the virtual machine. Generally used for `HogValue::deref`, to allow you to access
    /// `HogLiteral` values for native function implementation.
    pub heap: VmHeap, // Needs to be pub to allow users to write their own extension native functions
    stack: Vec<HogValue>,

    stack_frames: Vec<CallFrame>,
    throw_frames: Vec<ThrowFrame>,
    // Upvalues still open (viewing a live stack slot). Closures created in this scope share these
    // cells; when a slot leaves scope (stack truncation) the matching upvalue is closed (snapshotted)
    // and removed from here. See `capture_upvalue` / `close_upvalues`.
    open_upvalues: Vec<UpvalueCell>,
    ip: usize,
    // How many times this run has suspended on an async function call. Carried into snapshots and
    // restored on resume, so the per-run async budget survives the suspend/resume round-trip.
    async_steps: usize,
    // Count of opcodes dispatched this run (the reference's `ops`). Carried across suspend/resume.
    ops: usize,
    // Per-opcode execution trace, collected only when the context opts into telemetry. Each entry is
    // the reference's `[time, chunk, ip, "op/NAME", debug]` tuple. Carried across suspend/resume.
    telemetry: Vec<JsonValue>,

    context: &'a ExecutionContext,
    // The base program is None, but calling into e.g. hog standard library functions involves changing the "module"
    // the pointer is currently pointing into to e.g. "arrayExists", as part of the function call that branches into
    // that function.
    current_symbol: Option<Symbol>,
}

struct CallFrame {
    ret_ptr: usize,             // Where to jump back to when we're done
    ret_symbol: Option<Symbol>, // The module to return to when we're done
    stack_start: usize,         // Point in the stack the frame values start
    // The closure this frame is running (its callable + captured upvalues). Captures are read by
    // `frame_capture`; the callable identity is what lets a snapshot reconstruct the reference VM's
    // per-frame `closure`. Cross-module (STL) frames synthesize a callable for their symbol.
    closure: Closure,
}

struct ThrowFrame {
    catch_ptr: usize,             // The ptr to jump to if we throw
    catch_symbol: Option<Symbol>, // The module to return to if we throw
    stack_start: usize,           // The stack size when we entered the try
    call_depth: usize,            // The depth of the call stack when we entered the try
}

impl<'a> HogVM<'a> {
    pub fn new(context: &'a ExecutionContext) -> Result<Self, VmError> {
        Ok(Self {
            stack: Vec::new(),
            stack_frames: Vec::new(),
            throw_frames: Vec::new(),
            open_upvalues: Vec::new(),
            ip: 0,
            async_steps: 0,
            ops: 0,
            telemetry: Vec::new(),
            current_symbol: None,
            context,
            heap: VmHeap::new(context.max_heap_size),
        })
    }

    /// Step the virtual machine, writing some debug information to the provided output function.
    pub fn debug_step(&mut self, output: &dyn Fn(String)) -> Result<StepOutcome, VmError> {
        let op: Operation = self.next()?;
        let mut surrounding = Vec::new();
        let start = self.ip.saturating_sub(2);
        for i in 0..5 {
            if let Ok(op) = self.context.get_bytecode(start + i, &self.current_symbol) {
                surrounding.push(op);
            }
        }

        self.ip -= 1;
        output(format!(
            "Op ({}), module {:?}: {:?} [{:?}], Stack: {:?}",
            self.ip, self.current_symbol, op, surrounding, self.stack
        ));
        self.step()
    }

    /// Step the virtual machine one cycle.
    pub fn step(&mut self) -> Result<StepOutcome, VmError> {
        let pre_ip = self.ip;
        let op: Operation = match self.next() {
            Ok(op) => op,
            // The reference VMs halt gracefully when the instruction pointer runs off the
            // end of the top-level program (it has no trailing RETURN), yielding the top of
            // stack or null. Only do this at the top level — running off the end inside a
            // function/module is still malformed bytecode.
            Err(VmError::EndOfProgram(_))
                if self.stack_frames.is_empty() && self.current_symbol.is_none() =>
            {
                let result = if self.stack.is_empty() {
                    HogLiteral::Null.into()
                } else {
                    self.pop_stack()?
                };
                return Ok(StepOutcome::Finished(self.hog_to_json(&result)?));
            }
            Err(e) => return Err(e),
        };

        self.ops += 1;

        if self.context.collect_telemetry {
            // The reference's `[time, chunk, ip, "op/NAME", debug]`. Time is a placeholder (we don't
            // expose a wall clock here) and debug is unused; the chunk/ip/op trace is the substance.
            self.telemetry.push(json!([
                0,
                chunk_str(&self.current_symbol),
                self.node_ip(pre_ip, &self.current_symbol),
                op_telemetry_name(&op),
                "",
            ]));
        }

        match op {
            Operation::GetGlobal => {
                // GetGlobal is used to do 1 of 2 things, either push a value from a global variable onto the stack, or push a new
                // function reference (referred to in other impls as a "closure") onto the stack - either a native one, or a hog one
                let mut chain = Vec::new();
                let count: usize = self.next()?;
                for _ in 0..count {
                    chain.push(self.pop_stack()?);
                }
                if chain.is_empty() {
                    return Err(VmError::UnknownGlobal("".to_string()));
                }

                // Copy out the `Copy` `&ExecutionContext` so the `found` borrow is tied to it, not to
                // `self` — leaving `self` free for the `&mut self` `json_to_hog` call below.
                let context = self.context;
                if let Some(found) = get_json_nested(&context.globals, &chain, self)? {
                    let val = self.json_to_hog(found)?;
                    self.push_stack(val)?;
                } else if let Ok(closure) = self.get_fn_reference(&chain) {
                    self.push_stack(closure)?;
                } else if get_json_nested(&context.globals, &chain[..1], self)?.is_some() {
                    // If the first element of the chain is a global, push null onto the stack, e.g.
                    // if a program is looking for "properties.blah", and "properties" exists, but
                    // "blah" doesn't, push null onto the stack.
                    self.push_stack(HogLiteral::Null)?;
                } else {
                    // But if the first element in the chain didn't exist, this is an error (the mental model here
                    // comes from SQL, where a missing column is an error, but a missing field in a column is, or
                    // at least can be, treated as a null value).
                    return Err(VmError::UnknownGlobal(format!("{chain:?}")));
                }
            }
            // We don't implement DeclareFn, because it's not used in the current compiler - it uses
            // "callables" constructed on the stack, which are then called by constructing a "closure",
            // which is basically a function call that wraps a "callable" and populates it's argument list
            Operation::DeclareFn => return Err(VmError::NotImplemented("DeclareFn".to_string())),
            Operation::CallGlobal => {
                // The TS impl here has a bunch of special case handling for functions with particular names.
                // I'm hoping I can simplify that here by unifying the native call interface a bit
                let name: String = self.next()?;
                let arg_count: usize = self.next()?;
                // NOTE - the TS implementation has a clause here that looks for the name in the
                // "declared functions" - basically, the legacy way of declaring a function before Callable
                // and closures were introduced. We leave it out because, as above, DeclareFn isn't supported
                let available_args = self.stack.len() - self.current_frame_base();
                if available_args < arg_count {
                    return Err(VmError::NotEnoughArguments(name, available_args, arg_count));
                }
                let symbol = Symbol::new("stl", &name);
                if self.context.has_symbol(&symbol) {
                    // Cross module calls are done in a manner very similar to CallLocal, just with some
                    // messing around with the current state module.
                    return self.prep_cross_module_call(symbol, arg_count);
                }

                let mut args = Vec::with_capacity(arg_count);
                for _ in 0..arg_count {
                    args.push(self.pop_stack()?);
                }
                if self.context.version() != 0 {
                    // In v0, the arguments were expected to be passed in
                    // stack pop order, not push order. We simulate that here
                    // but always popping, but then maybe reversing
                    args.reverse();
                }
                // This VM does native calls like so: it returns a "native call" struct, which the
                // executing environment dispatches — inline for a native, or as a suspension for a
                // registered async function (handled in the resumable driver).
                return Ok(self.prep_native_call(name, args));
            }
            Operation::And => {
                let count: usize = self.next()?;
                let mut acc: HogLiteral = true.into();
                for _ in 0..count {
                    let value = self.pop_stack()?;
                    let value = value.deref(&self.heap)?;
                    acc = acc.and(value)?;
                }
                self.push_stack(acc)?;
            }
            Operation::Or => {
                let count: usize = self.next()?;
                let mut acc: HogLiteral = false.into();
                for _ in 0..count {
                    let value = self.pop_stack()?;
                    let value = value.deref(&self.heap)?;
                    acc = acc.or(value)?;
                }
                self.push_stack(acc)?;
            }
            Operation::Not => {
                let val = self.pop_stack()?;
                let result = val.deref(&self.heap)?.not()?;
                self.push_stack(result)?;
            }
            Operation::Plus => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Add, &a, &b)?)?;
            }
            Operation::Minus => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Sub, &a, &b)?)?;
            }
            Operation::Mult => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Mul, &a, &b)?)?;
            }
            Operation::Div => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Div, &a, &b)?)?;
            }
            Operation::Mod => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Mod, &a, &b)?)?;
            }
            Operation::Eq => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                let result = self.eq_op(&a, &b)?;
                self.push_stack(result)?;
            }
            Operation::NotEq => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                let result = self.eq_op(&a, &b)?.not()?;
                self.push_stack(result)?;
            }
            Operation::Gt => self.compare_op(NumOp::Gt)?,
            Operation::GtEq => self.compare_op(NumOp::Gte)?,
            Operation::Lt => self.compare_op(NumOp::Lt)?,
            Operation::LtEq => self.compare_op(NumOp::Lte)?,
            Operation::Like => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(like(val, pat, true)?)?;
            }
            Operation::Ilike => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(like(val, pat, false)?)?;
            }
            Operation::NotLike => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(!like(val, pat, true)?)?;
            }
            Operation::NotIlike => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(!like(val, pat, false)?)?;
            }
            Operation::In => {
                let (needle, haystack) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(haystack.contains(&needle, &self.heap)?)?;
            }
            Operation::NotIn => {
                let (needle, haystack) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(haystack.contains(&needle, &self.heap)?.not()?)?;
            }
            Operation::Regex => self.regex_op(true, false)?,
            Operation::NotRegex => self.regex_op(true, true)?,
            Operation::Iregex => self.regex_op(false, false)?,
            Operation::NotIregex => self.regex_op(false, true)?,
            Operation::InCohort => return Err(VmError::NotImplemented("InCohort".to_string())),
            Operation::NotInCohort => {
                return Err(VmError::NotImplemented("NotInCohort".to_string()))
            }
            Operation::True => {
                self.push_stack(true)?;
            }
            Operation::False => {
                self.push_stack(false)?;
            }
            Operation::Null => {
                self.push_stack(HogLiteral::Null)?;
            }
            Operation::String => {
                let val: String = self.next()?;
                self.push_stack(val)?;
            }
            Operation::Float => {
                let val: f64 = self.next()?;
                self.push_stack(val)?;
            }
            // The reference's INTEGER opcode is untyped `pushStack(next())`; the SQL-AST compiler
            // emits it with a boolean operand. Fast-path the overwhelmingly common i64 (this is a hot
            // opcode — loop counters etc.), and fall back to pushing the raw token for anything else.
            Operation::Integer => {
                let as_int = self
                    .context
                    .get_bytecode(self.ip, &self.current_symbol)?
                    .as_i64();
                if let Some(i) = as_int {
                    self.ip += 1;
                    self.push_stack(i)?;
                } else {
                    let token = self
                        .context
                        .get_bytecode(self.ip, &self.current_symbol)?
                        .clone();
                    self.ip += 1;
                    let val = self.json_to_hog(&token)?;
                    self.push_stack(val)?;
                }
            }
            Operation::Pop => {
                self.pop_stack()?;
            }
            Operation::GetLocal => {
                let base = self.current_frame_base();
                // Usize as a positive offset from the current frame
                let offset: usize = self.next()?;
                let ptr = self.hoist(base.checked_add(offset).ok_or(VmError::IntegerOverflow)?)?;
                self.push_stack(ptr)?;
            }
            Operation::SetLocal => {
                // Replace some item "lower" in the stack with the top one.
                let base = self.current_frame_base();
                // Usize as a positive offset from the current frame
                let offset: usize = self.next()?;
                let value = self.pop_stack()?;
                self.set_stack_val(
                    base.checked_add(offset).ok_or(VmError::IntegerOverflow)?,
                    value,
                )?;
            }
            Operation::Return => {
                let result = self.pop_stack()?;
                let last_frame = self.stack_frames.pop();
                let Some(frame) = last_frame else {
                    return Ok(StepOutcome::Finished(self.hog_to_json(&result)?));
                };

                // NOTE - this diverges from the TS impl
                // if self.stack_frames.is_empty() {
                //     return Ok(StepOutcome::Finished(result.deref(&self.heap)?.clone()));
                // };
                //
                self.current_symbol = frame.ret_symbol;
                self.truncate_stack(frame.stack_start)?;
                self.ip = frame.ret_ptr;
                self.push_stack(result)?;
            }
            Operation::Jump => {
                // i32 to permit branching backwards
                let offset: i32 = self.next()?;
                self.ip = ((self.ip as i64)
                    .checked_add(offset as i64)
                    .ok_or(VmError::IntegerOverflow)?) as usize;
            }
            Operation::JumpIfFalse => {
                // i32 to permit branching backwards
                let offset: i32 = self.next()?;
                // The reference coerces with `!popStack()`, so any falsy value (0, "", null, …) branches.
                let val = self.pop_stack()?;
                if !val.deref(&self.heap)?.truthy() {
                    self.ip = ((self.ip as i64)
                        .checked_add(offset as i64)
                        .ok_or(VmError::IntegerOverflow)?) as usize;
                }
            }
            Operation::JumpIfStackNotNull => {
                // i32 to permit branching backwards
                let offset: i32 = self.next()?;
                // Weirdly, this operation doesn't pop the value from the stack. This is mostly a random choice.
                if !self.stack.is_empty() {
                    let item = self.clone_stack_item(self.stack.len() - 1)?;
                    let item = item.deref(&self.heap)?;
                    if !matches!(item, HogLiteral::Null) {
                        self.ip = ((self.ip as i64)
                            .checked_add(offset as i64)
                            .ok_or(VmError::IntegerOverflow)?)
                            as usize;
                    }
                }
            }
            Operation::Dict => {
                let element_count: usize = self.next()?;
                let mut keys = Vec::with_capacity(element_count);
                let mut values = Vec::with_capacity(element_count);
                // The keys and values are pushed into the stack in key:value, key:value pairs, but we're
                // going to walk the stack backwards to construct the dictionary
                for _ in 0..element_count {
                    // Note we don't put references into collections ever
                    values.push(self.pop_stack()?);
                    keys.push(self.pop_stack_as::<String>()?);
                }
                // keys/values were popped in reverse (stack order), so reverse the zip to restore
                // the source insertion order in the IndexMap.
                let map: IndexMap<String, HogValue> = keys.into_iter().zip(values).rev().collect();
                let obj = HogLiteral::Object(map);
                // For the non-primitive types below (objects, arrays, "tuples"), we /always/ heap allocate them. The reason
                // is that the pattern for e.g. nestedly setting an array value is to GetLocal followed by GetProperty, followed
                // by a SetProperty. If the array is "flat", as in, element 3 is a HogLiteral rather than Value, that SetProperty
                // will do nothing, because there's nowhere to write the new value /to/ (as the stack copy of the literal array would be
                // immediately dropped). We assert in SetProperty that the target is a reference, in order to prevent this surprising no-op
                // behaviour, but that means we have to either always heap-allocate our indexable values, or hoist in GetProperty. I've decided
                // to pay the cost of heap-allocating them up-front (and therefore chasing an extra pointer), because I think it more closely
                // mirrors the semantics of e.g. JavaScript or Python, which is what hog is based around.
                let ptr = self.heap.emplace(obj)?;
                self.push_stack(ptr)?;
            }
            Operation::Array => {
                let element_count: usize = self.next()?;
                let mut elements = Vec::with_capacity(element_count);
                for _ in 0..element_count {
                    elements.push(self.pop_stack()?);
                }
                // We've walked back down the stack, but the compiler expects the array to be in pushed order
                elements.reverse();
                let array = HogLiteral::Array(elements);
                // See above
                let ptr = self.heap.emplace(array)?;
                self.push_stack(ptr)?;
            }
            Operation::Tuple => {
                // A tuple behaves like an array but prints as `(a, b)` and has typeof "tuple", so it
                // gets its own literal variant rather than reusing Array.
                let element_count: usize = self.next()?;
                let mut elements = Vec::with_capacity(element_count);
                for _ in 0..element_count {
                    elements.push(self.pop_stack()?);
                }
                // We've walked back down the stack, but the compiler expects the tuple in pushed order
                elements.reverse();
                let tuple = HogLiteral::Tuple(elements);
                let ptr = self.heap.emplace(tuple)?;
                self.push_stack(ptr)?;
            }
            // Both reference VMs (`getNestedValue`/`get_nested_value`) return null for a missing
            // object key or out-of-range array index — the `nullish` flag only short-circuits a
            // null *intermediate* in a multi-key chain, which these single-key opcodes never hit.
            // So plain GetProperty and GetPropertyNullish behave identically here: null on miss.
            Operation::GetProperty | Operation::GetPropertyNullish => {
                let needle = self.pop_stack()?;
                let haystack = self.pop_stack()?;
                let chain = [needle];
                let res = haystack
                    .get_nested(&chain, &self.heap)?
                    .cloned()
                    .unwrap_or(HogLiteral::Null.into());
                self.push_stack(res)?;
            }
            Operation::SetProperty => {
                // Set property is a little tricky, because it assumes the object whose property is being set is
                // a reference. We assert this here - basically, we don't allow SET_PROPERTY to be a no-op, unlike the
                // original implementation, which would allow SET_PROPERTY to be done even if the target was dropped immediately
                // after the operation
                // Value to set - this could be a literal or a reference
                let val = self.pop_stack()?;

                // Location to set it at in the target - this could be a literal or a reference, but
                // it doesn't matter which it is, we deref anyway as only literals can be object keys
                let key: HogLiteral = self.pop_stack_as()?;

                // This can be either a literal or a reference. If it's a reference, we have to deref_mut it
                // from the head, so we can modify it
                let mut target = self.pop_stack()?;
                let target = match &mut target {
                    HogValue::Ref(ptr) => self.heap.get_mut(*ptr)?,
                    HogValue::Lit(_) => {
                        // TODO - this is a divergence from the original implementation - basically, if the target you've specified isn't on the heap,
                        // we'll drop it immediately after setting the property, which is a no-op. This should never happen - we should be using GET_LOCAL
                        // to hoist properties onto the heap before calling SET_PROPERTY, I /think/, but I'm not certain. I might end up making all
                        // objects be auto-allocated on the heap, just to be certain we're never hit this case for anything set_property() would succeed for
                        return Err(VmError::ExpectedObject);
                    }
                };

                let mut allocated_bytes = val.size();
                let key_bytes = key.size();
                let freed_bytes = target.set_property(key, val)?;
                if freed_bytes == 0 {
                    allocated_bytes += key_bytes; // We inserted a new key as well as a new prop
                }

                // This doesn't assert the allocation is possible - the next one will fail, which is good enough
                let new_bytes = self
                    .heap
                    .current_bytes
                    .saturating_sub(freed_bytes)
                    .saturating_add(allocated_bytes);
                self.heap.set_current_bytes(new_bytes);
            }
            Operation::Try => {
                // i32 to permit setting a catch offset lower than the IP
                let catch_offset: i32 = self.next()?;
                // The reference computes `catchIp = <TRY position> + 1 + offset`. After reading the
                // opcode and offset, self.ip points two past the TRY position, so subtract one to land
                // on the same instruction (the compiler's offset already skips the POP_TRY).
                let catch_ip = (self.ip as i64)
                    .checked_add(catch_offset as i64 - 1)
                    .ok_or(VmError::IntegerOverflow)? as usize;
                let frame = ThrowFrame {
                    catch_ptr: catch_ip,
                    catch_symbol: self.current_symbol.clone(),
                    stack_start: self.stack.len(),
                    call_depth: self.stack_frames.len(),
                };
                self.throw_frames.push(frame);
            }
            Operation::PopTry => {
                if self.throw_frames.pop().is_none() {
                    return Err(VmError::UnexpectedPopTry);
                };
            }
            Operation::Throw => {
                let exception = self.pop_stack()?;
                let type_key: HogValue = HogLiteral::from("type".to_string()).into();
                let _type = exception.get_nested(&[type_key], &self.heap)?;
                let message_key = HogLiteral::from("message".to_string()).into();
                let message = exception.get_nested(&[message_key], &self.heap)?;
                // The other impls here have some special case handling that treats "Error" as a distinct type, but
                // as far as I can tell, a "hog error" is just a HogValue::Object with some specific properties, so
                // I'll just check those exist. hog is mostly duck-typed, based on the existing impls
                if _type.is_none() || message.is_none() {
                    return Err(VmError::InvalidException);
                };

                let Some(frame) = self.throw_frames.pop() else {
                    // TODO - we need some helper that'll deeply clone a HogValue::Object and product a HashMap<String, HogLiteral>, since
                    // this is escaping the VM, so heap references can't leak.
                    // let payload_key = HogLiteral::from("payload".to_string()).into();
                    // let payload = exception.get_nested(&[payload_key], &self.heap)?;
                    let _type: &str = _type.unwrap().deref(&self.heap)?.try_as()?;
                    let _message: &str = message.unwrap().deref(&self.heap)?.try_as()?;
                    return Err(VmError::UncaughtException(
                        _type.to_string(),
                        _message.to_string(),
                    ));
                };

                self.truncate_stack(frame.stack_start)?;
                self.stack_frames.truncate(frame.call_depth);
                self.ip = frame.catch_ptr;
                self.current_symbol = frame.catch_symbol;
                self.push_stack(exception)?;
            }
            Operation::Callable => {
                // Construct a locally callable object - this is how e.g. fn decl's work
                let name: String = self.next()?;
                let stack_arg_count: usize = self.next()?;
                let captured_arg_count: usize = self.next()?;
                let body_length: usize = self.next()?;
                let callable: Callable = LocalCallable {
                    name,
                    stack_arg_count,
                    capture_count: captured_arg_count,
                    ip: self.ip,
                    symbol: self.current_symbol.clone(), // Cross-module jumps are currently only done via CallGlobal
                }
                .into();
                self.push_stack(HogLiteral::Callable(callable))?;
                self.ip = self
                    .ip
                    .checked_add(body_length)
                    .ok_or(VmError::IntegerOverflow)?;
            }
            // A closure is a callable, plus some captured arguments from the scope
            // it was constructed in.
            Operation::Closure => {
                let callable: Callable = self.pop_stack_as()?;
                let capture_count: usize = self.next()?;
                // Only hog-local callables are wrapped by the CLOSURE opcode; native (STL) callables
                // are produced already-closed by GetGlobal, so they should never reach here.
                let Callable::Local(unwrapped) = &callable else {
                    return Err(VmError::InvalidCall(
                        "cannot close over a native function".to_string(),
                    ));
                };
                // Because captures are an implicit part of compilation, it's never valid
                // for them to be different from the number of captures in the callable.
                if capture_count != unwrapped.capture_count {
                    return Err(VmError::InvalidCall(
                        "invalid number of heap arguments".to_string(),
                    ));
                }
                let mut captures = Vec::with_capacity(capture_count);
                for _ in 0..capture_count {
                    // Indicates whether this captured value is a local in this frame's stack, or an
                    // upvalue already captured by this frame's closure.
                    let is_local: bool = self.next()?;
                    let offset: usize = self.next()?;
                    if is_local {
                        let location = self
                            .current_frame_base()
                            .checked_add(offset)
                            .ok_or(VmError::IntegerOverflow)?;
                        captures.push(self.capture_upvalue(location));
                    } else {
                        // Nested closure: share the parent frame's upvalue cell.
                        captures.push(self.frame_capture(offset)?);
                    }
                }

                let closure = Closure { callable, captures };
                self.push_stack(HogLiteral::Closure(closure))?;
            }
            Operation::CallLocal => {
                let closure: Closure = self.pop_stack_as()?;
                let arg_count: usize = self.next()?;
                // Extract the scalar callable fields up front so `closure` can be moved into the frame
                // (which now retains it for snapshotting). A native-function value dispatches inline.
                let (ip, symbol, stack_arg_count) = match &closure.callable {
                    Callable::Local(callable) => (
                        callable.ip,
                        callable.symbol.clone(),
                        callable.stack_arg_count,
                    ),
                    // A first-class native function value (e.g. `let f := base64Encode; f(x)`):
                    // pop the args (push order, reversed for v>0 like CallGlobal) and dispatch natively.
                    Callable::Stl(name) => {
                        let name = name.clone();
                        let mut args = Vec::with_capacity(arg_count);
                        for _ in 0..arg_count {
                            args.push(self.pop_stack()?);
                        }
                        if self.context.version() != 0 {
                            args.reverse();
                        }
                        return Ok(self.prep_native_call(name, args));
                    }
                };
                if arg_count > stack_arg_count {
                    return Err(VmError::InvalidCall(format!(
                        "Too many args - expected {stack_arg_count}, got {arg_count}"
                    )));
                }
                let null_args = stack_arg_count.saturating_sub(arg_count);
                // For pure-hog function calls (calls to "local" callables), we just push a null onto the stack for each missing argument,
                // then construct the stack frame, and jump to the callable's frame ip. For other kinds of calls (which we don't support yet),
                // we'll have to do something more complicated
                for _ in 0..null_args {
                    self.push_stack(HogLiteral::Null)?;
                }
                let frame = CallFrame {
                    ret_ptr: self.ip,
                    ret_symbol: self.current_symbol.clone(),
                    stack_start: self.stack.len().saturating_sub(stack_arg_count),
                    closure,
                };
                self.stack_frames.push(frame);
                self.current_symbol = symbol; // Prep to jump across the module boundary, if that's what we're doing
                self.ip = ip; // Do the jump
            }
            Operation::GetUpvalue => {
                let index: usize = self.next()?;
                let cell = self.frame_capture(index)?;
                // Open: read through to the live stack slot. Closed: read the snapshot it owns.
                let val = {
                    let uv = cell.borrow();
                    if uv.closed {
                        uv.value.clone().unwrap_or_else(|| HogLiteral::Null.into())
                    } else {
                        self.stack
                            .get(uv.location)
                            .cloned()
                            .ok_or(VmError::StackIndexOutOfBounds)?
                    }
                };
                self.push_stack(val)?;
            }
            Operation::SetUpvalue => {
                let index: usize = self.next()?;
                let cell = self.frame_capture(index)?;
                let val = self.pop_stack()?;
                // Open: write through to the live stack slot. Closed: store into the snapshot.
                let (closed, location) = {
                    let uv = cell.borrow();
                    (uv.closed, uv.location)
                };
                if closed {
                    cell.borrow_mut().value = Some(val);
                } else {
                    self.set_stack_val(location, val)?;
                }
            }
            Operation::CloseUpvalue => {
                // Reference: `stackKeepFirstElements(stack.length - 1)` — close any upvalue viewing
                // the top slot (snapshot it), then drop the slot.
                let new_len = self.stack.len().saturating_sub(1);
                self.truncate_stack(new_len)?;
            }
        }

        Ok(StepOutcome::Continue)
    }

    // Returns the first stack item in this call frames scope
    fn current_frame_base(&self) -> usize {
        if self.stack_frames.is_empty() {
            0
        } else {
            self.stack_frames[self.stack_frames.len() - 1].stack_start
        }
    }

    // The upvalue cell captured at `index` by the currently-executing closure.
    fn frame_capture(&self, index: usize) -> Result<UpvalueCell, VmError> {
        let Some(frame) = self.stack_frames.last() else {
            return Err(VmError::NoFrame);
        };
        frame
            .closure
            .captures
            .get(index)
            .cloned()
            .ok_or(VmError::CaptureOutOfBounds(index))
    }

    // Capture the stack slot at `location` as an open upvalue, deduplicating so all closures that
    // capture the same live slot share one cell (and therefore observe the same close). Matches the
    // reference's `captureUpValue`.
    fn capture_upvalue(&mut self, location: usize) -> UpvalueCell {
        if let Some(existing) = self
            .open_upvalues
            .iter()
            .find(|cell| cell.borrow().location == location)
            .cloned()
        {
            return existing;
        }
        let cell = Rc::new(RefCell::new(Upvalue {
            location,
            closed: false,
            value: None,
        }));
        self.open_upvalues.push(cell.clone());
        cell
    }

    // Close every open upvalue whose slot is at or above `from` (i.e. about to leave scope):
    // snapshot the current stack value into the cell and drop it from the open list. The closures
    // holding the cell keep the snapshot. Matches the reference's `stackKeepFirstElements` close loop.
    fn close_upvalues(&mut self, from: usize) {
        if self.open_upvalues.is_empty() {
            return;
        }
        let mut i = 0;
        while i < self.open_upvalues.len() {
            let location = self.open_upvalues[i].borrow().location;
            if location >= from {
                let snapshot = self
                    .stack
                    .get(location)
                    .cloned()
                    .unwrap_or_else(|| HogLiteral::Null.into());
                {
                    let mut uv = self.open_upvalues[i].borrow_mut();
                    uv.closed = true;
                    uv.value = Some(snapshot);
                }
                self.open_upvalues.swap_remove(i);
            } else {
                i += 1;
            }
        }
    }

    fn next<T>(&mut self) -> Result<T, VmError>
    where
        T: DeserializeOwned + Any,
    {
        let next = self.context.get_bytecode(self.ip, &self.current_symbol)?;
        self.ip += 1;
        // Borrow-deserialize straight from the &JsonValue (serde_json implements Deserializer for
        // &Value) instead of cloning the whole value and deserializing an owned copy on every
        // single instruction fetch. The error type-name strings are built lazily, only on an actual
        // mismatch, rather than allocating one per token read on the hot path.
        T::deserialize(next).map_err(|_| {
            VmError::InvalidValue(next_type_name(next), std::any::type_name::<T>().to_string())
        })
    }

    fn pop_stack(&mut self) -> Result<HogValue, VmError> {
        if self.stack.len() <= self.current_frame_base() {
            return Err(VmError::StackUnderflow);
        }
        self.stack.pop().ok_or(VmError::StackUnderflow)
    }

    // As above, but with a handy pointer chase and a cast/unwrap. Necessarily clones
    // if the stack item was a reference.
    fn pop_stack_as<T>(&mut self) -> Result<T, VmError>
    where
        T: FromHogLiteral,
    {
        match self.pop_stack()? {
            HogValue::Lit(lit) => lit.try_into(), // Purely an optimisation to skip a clone
            other => other.deref(&self.heap)?.clone().try_into(),
        }
    }

    /// `Gt`/`GtEq`/`Lt`/`LtEq` arm. The default (legacy) path requires numeric operands and errors
    /// otherwise — the behavior `cymbal` and every other existing shared-crate consumer relies on
    /// (a non-number operand erroring is what lets cymbal auto-disable a malformed rule). Only when
    /// the context opts into coercing comparisons (the realtime-cohort evaluator, via
    /// [`ExecutionContext::with_coercing_comparisons`](crate::ExecutionContext::with_coercing_comparisons))
    /// does a non-`Number` operand reach [`compare_values`]' coercion instead of erroring. `a` is the
    /// top of the stack.
    // `=~`/`!~` (and the case-insensitive variants). The stack holds the pattern below the value;
    // either operand being null never matches (the reference's external matcher returns false), so
    // `=~` is false and `!~` is true.
    fn regex_op(&mut self, case_sensitive: bool, negate: bool) -> Result<(), VmError> {
        let val = self.pop_stack()?;
        let pat = self.pop_stack()?;
        let matched = {
            let val_lit = val.deref(&self.heap)?;
            let pat_lit = pat.deref(&self.heap)?;
            if matches!(val_lit, HogLiteral::Null) || matches!(pat_lit, HogLiteral::Null) {
                false
            } else {
                regex_match(
                    val_lit.try_as::<str>()?,
                    pat_lit.try_as::<str>()?,
                    case_sensitive,
                )?
            }
        };
        self.push_stack(HogLiteral::Boolean(matched ^ negate))
    }

    fn compare_op(&mut self, op: NumOp) -> Result<(), VmError> {
        if !self.context.coerce_comparisons {
            // Legacy/reference path: both operands must be `Number` or this errors.
            let (a, b): (Num, Num) = (self.pop_stack_as()?, self.pop_stack_as()?);
            return self.push_stack(Num::binary_op(op, &a, &b)?);
        }
        let a = self.pop_stack()?;
        let b = self.pop_stack()?;
        // Scope the immutable heap borrows so the result is owned before the `&mut self` push.
        let result = {
            let a_lit = a.deref(&self.heap)?;
            let b_lit = b.deref(&self.heap)?;
            compare_values(op, a_lit, b_lit, &self.heap)?
        };
        self.push_stack(result)
    }

    /// `Eq`/`NotEq` core. The default path is the legacy structural equality every existing
    /// shared-crate consumer relies on. Only when the context opts into coercing comparisons (the
    /// realtime-cohort evaluator) do two Hog temporals compare by epoch seconds to match ClickHouse
    /// (`is_date_exact`); every non-temporal pair is unchanged either way.
    fn eq_op(&self, a: &HogValue, b: &HogValue) -> Result<HogLiteral, VmError> {
        if self.context.coerce_comparisons {
            let (lhs, rhs) = (a.deref(&self.heap)?, b.deref(&self.heap)?);
            if let (Some(x), Some(y)) = (
                lhs.as_temporal_seconds(&self.heap),
                rhs.as_temporal_seconds(&self.heap),
            ) {
                return Ok((x == y).into());
            }
        }
        a.equals(b, &self.heap)
    }

    // Move a value from the stack onto the heap, replacing it with a reference to the heap value,
    // and returning a reference to it. If it was already a reference, return it.
    fn hoist(&mut self, idx: usize) -> Result<HeapReference, VmError> {
        let item = self.clone_stack_item(idx)?;
        match item {
            HogValue::Lit(lit) => {
                let ptr = self.heap.emplace(lit)?;
                self.set_stack_val(idx, ptr)?;
                Ok(ptr)
            }
            HogValue::Ref(ptr) => Ok(ptr),
        }
    }

    fn set_stack_val(&mut self, idx: usize, value: impl Into<HogValue>) -> Result<(), VmError> {
        // TODO - revisit this, idk about it
        self.stack
            .get_mut(idx)
            .ok_or(VmError::StackIndexOutOfBounds)
            .map(|v| *v = value.into())
    }

    fn truncate_stack(&mut self, new_len: usize) -> Result<(), VmError> {
        if new_len > self.stack.len() {
            return Err(VmError::StackIndexOutOfBounds);
        }
        // Any upvalue viewing a slot that's about to disappear must be closed (snapshotted) first,
        // so closures that captured it keep the value rather than a dangling stack index.
        self.close_upvalues(new_len);
        self.stack.truncate(new_len);
        Ok(())
    }

    pub(crate) fn push_stack(&mut self, value: impl Into<HogValue>) -> Result<(), VmError> {
        if self.stack.len() >= self.context.max_stack_depth {
            return Err(VmError::StackOverflow);
        }
        self.stack.push(value.into());
        Ok(())
    }

    // TODO - we don't support function imports right now - most trivial programs don't need them,
    // and filters are generally trivial
    // Resolve a global name referenced as a first-class function value. Currently supports native
    // (STL) functions — `let f := base64Encode` yields a closure that dispatches to the native fn.
    fn get_fn_reference(&self, chain: &[HogValue]) -> Result<HogLiteral, VmError> {
        if chain.len() != 1 {
            return Err(VmError::NotImplemented("imports".to_string()));
        }
        let name: &str = chain[0].deref(&self.heap)?.try_as()?;
        if self.context.has_native(name) {
            return Ok(HogLiteral::Closure(Closure {
                callable: Callable::Stl(name.to_string()),
                captures: Vec::new(),
            }));
        }
        Err(VmError::NotImplemented("imports".to_string()))
    }

    fn clone_stack_item(&self, idx: usize) -> Result<HogValue, VmError> {
        self.stack.get(idx).cloned().ok_or(VmError::StackUnderflow)
    }

    fn prep_native_call(&self, name: String, args: Vec<HogValue>) -> StepOutcome {
        StepOutcome::NativeCall(name, args)
    }

    fn prep_cross_module_call(
        &mut self,
        symbol: Symbol,
        arg_count: usize,
    ) -> Result<StepOutcome, VmError> {
        // See CallLocal for details on how this works, but effectively, a cross-module call is just a
        // local call plus a current "module/function" change
        let to_call = self.context.get_symbol(&symbol)?;
        if arg_count > to_call.arg_count() {
            return Err(VmError::InvalidCall(format!(
                "Too many args - expected {}, got {}",
                to_call.arg_count(),
                arg_count
            )));
        }
        let callee_arg_count = to_call.arg_count();
        let null_args = callee_arg_count.saturating_sub(arg_count);
        for _ in 0..null_args {
            self.push_stack(HogLiteral::Null)?;
        }
        // Cross-module calls never involve captures, but the frame still carries a synthesized
        // callable for its symbol so a snapshot can render the reference VM's per-frame closure
        // (e.g. `fn<arrayMap>` in chunk `stl/arrayMap`).
        let frame = CallFrame {
            ret_ptr: self.ip,
            ret_symbol: self.current_symbol.clone(),
            stack_start: self.stack.len().saturating_sub(callee_arg_count),
            closure: Closure {
                callable: Callable::Local(LocalCallable {
                    name: symbol.name.clone(),
                    stack_arg_count: callee_arg_count,
                    capture_count: 0,
                    ip: 0,
                    symbol: Some(symbol.clone()),
                }),
                captures: Vec::new(),
            },
        };

        self.stack_frames.push(frame);
        self.current_symbol = Some(symbol);
        self.ip = 0;

        Ok(StepOutcome::Continue)
    }

    // Construct a hog value from a Json object. If the json object would be heap allocated
    // as a HogValue (e.g. if it's an array or object), then it will be allocated onto the heap,
    // and a reference will be returned. Nested json objects are flattened during allocation,
    // such that e.g. [[1,2],[3,4]] would lead to an array of [HeapReference, HeapReference] being
    // put into the heap, and a HeapReference being returned.
    //
    // This is a function on the VM, rather than being standalone, because hog values don't really
    // exist outside of the context of a VM (and specifically a heap). It could be a function on the
    // heap itself, though.
    pub fn json_to_hog(&mut self, json: &JsonValue) -> Result<HogValue, VmError> {
        self.json_to_hog_impl(json, 0)
    }

    fn json_to_hog_impl(&mut self, current: &JsonValue, depth: usize) -> Result<HogValue, VmError> {
        if depth > MAX_JSON_SERDE_DEPTH {
            return Err(VmError::OutOfResource(
                "json->hog deserialization depth".to_string(),
            ));
        };

        // Clone only the scalar leaves (numbers/strings); containers are walked by reference and
        // rebuilt onto the heap.
        match current {
            JsonValue::Null => Ok(HogLiteral::Null.into()),
            JsonValue::Bool(b) => Ok(HogLiteral::Boolean(*b).into()),
            JsonValue::Number(n) => Ok(HogLiteral::Number(n.clone().into()).into()),
            JsonValue::String(s) => Ok(HogLiteral::String(s.clone()).into()),
            JsonValue::Array(arr) => {
                let mut values = Vec::new();
                for value in arr {
                    values.push(self.json_to_hog_impl(value, depth + 1)?);
                }
                let to_emplace = HogLiteral::Array(values);
                let ptr = self.heap.emplace(to_emplace)?;
                Ok(ptr.into())
            }
            JsonValue::Object(obj) => {
                let mut map = IndexMap::new();
                for (key, value) in obj {
                    map.insert(key.clone(), self.json_to_hog_impl(value, depth + 1)?);
                }
                let to_emplace = HogLiteral::Object(map);
                let ptr = self.heap.emplace(to_emplace)?;
                Ok(ptr.into())
            }
        }
    }

    // Convert back from an arbitrary HogValue to a json Value. Again, this function exists on
    // the VM, because HogValues don't really exist in any other context.
    pub fn hog_to_json(&self, value: &HogValue) -> Result<JsonValue, VmError> {
        self.hog_to_json_impl(value, 0)
    }

    fn hog_to_json_impl(&self, value: &HogValue, depth: usize) -> Result<JsonValue, VmError> {
        if depth > MAX_JSON_SERDE_DEPTH {
            return Err(VmError::OutOfResource(
                "hog->json serialization depth".to_string(),
            ));
        };

        let val = value.deref(&self.heap)?;
        match val {
            HogLiteral::Null => Ok(JsonValue::Null),
            HogLiteral::Boolean(b) => Ok(JsonValue::Bool(*b)),
            HogLiteral::Number(n) => Ok(JsonValue::Number(n.clone().try_into()?)),
            HogLiteral::String(s) => Ok(JsonValue::String(s.clone())),
            HogLiteral::Array(arr) | HogLiteral::Tuple(arr) => {
                let mut json_arr = Vec::new();
                for elem in arr {
                    json_arr.push(self.hog_to_json_impl(elem, depth + 1)?);
                }
                Ok(JsonValue::Array(json_arr))
            }
            HogLiteral::Object(obj) => {
                let mut map = serde_json::Map::new();
                for (key, value) in obj {
                    map.insert(key.clone(), self.hog_to_json_impl(value, depth + 1)?);
                }
                Ok(JsonValue::Object(map))
            }
            HogLiteral::Callable(_) => Err(VmError::NotImplemented(
                "Callable serialisation".to_string(),
            )),
            HogLiteral::Closure(_) => {
                Err(VmError::NotImplemented("Closure serialisation".to_string()))
            }
        }
    }

    /// Capture the full live state as a serializable [`VmSnapshot`]. The program/STL are not part of
    /// the snapshot — [`resume`] re-supplies them via the `ExecutionContext`. The upvalue graph
    /// (`Rc<RefCell<Upvalue>>`, shared between the open list and closures) is flattened to ids.
    pub fn snapshot(&self) -> Result<VmSnapshot, VmError> {
        let mut registry = CellRegistry::default();
        // Intern open upvalues first (stable low ids), then everything reachable from the stack and
        // frame captures, then chase closed-cell values for nested closures.
        for cell in &self.open_upvalues {
            registry.intern(cell);
        }
        for value in &self.stack {
            collect_cells(value, &self.heap, &mut registry)?;
        }
        for frame in &self.stack_frames {
            for cell in &frame.closure.captures {
                registry.intern(cell);
            }
        }
        close_over_cells(&self.heap, &mut registry)?;

        // Read each cell's data out before serializing (so the value walk isn't aliasing the
        // registry it borrows; it is already complete, so no new ids are minted).
        let cell_data: Vec<(usize, bool, Option<HogValue>)> = registry
            .cells()
            .iter()
            .map(|c| {
                let b = c.borrow();
                (b.location, b.closed, b.value.clone())
            })
            .collect();

        let header_len = self.context.program_header_len();
        let mut stack = Vec::with_capacity(self.stack.len());
        for value in &self.stack {
            stack.push(value_to_json(value, &self.heap, &mut registry, header_len)?);
        }

        let mut upvalues = Vec::with_capacity(cell_data.len());
        for (id, (location, closed, value)) in cell_data.into_iter().enumerate() {
            let value_json = match (closed, &value) {
                (true, Some(v)) => value_to_json(v, &self.heap, &mut registry, header_len)?,
                _ => JsonValue::Null,
            };
            upvalues.push(UpvalueJson {
                marker: true,
                // 1-based, matching the reference (`id: sortedUpValues.length + 1`).
                id: id + 1,
                location,
                closed,
                value: value_json,
            });
        }

        // The reference keeps upvalues sorted by location so its capture early-break stays valid on
        // resume; each entry keeps its id so closure references still resolve.
        upvalues.sort_by_key(|u| u.location);

        let call_stack = self.build_call_stack(&mut registry, header_len)?;

        let throw_stack = self
            .throw_frames
            .iter()
            .map(|t| ThrowFrameJson {
                // The reference's callStackLen counts its frames — our depth plus the root frame.
                call_stack_len: t.call_depth + 1,
                stack_len: t.stack_start,
                catch_ip: self.node_ip(t.catch_ptr, &t.catch_symbol),
            })
            .collect();

        // The reference stores `bytecodes.root` as just `{ bytecode }` (globals are re-supplied via
        // options on resume), so omit globals to match its wire shape.
        Ok(VmSnapshot {
            bytecodes: json!({ "root": { "bytecode": self.context.program_tokens() } }),
            stack,
            upvalues,
            call_stack,
            throw_stack,
            declared_functions: json!({}),
            ops: self.ops,
            async_steps: self.async_steps,
            sync_duration: 0,
            max_mem_used: self.heap.peak_bytes,
            telemetry: self
                .context
                .collect_telemetry
                .then(|| self.telemetry.clone()),
        })
    }

    /// Build the reference's `callStack` (root frame first, active frame last). Frame `d` < N draws
    /// its ip/chunk from the frame pushed when depth `d` called `d+1` (which stored `d`'s resume
    /// point) and its closure/stackStart from that same callee frame; depth N is the live position.
    fn build_call_stack(
        &self,
        registry: &mut CellRegistry,
        header_len: usize,
    ) -> Result<Vec<CallFrameJson>, VmError> {
        let n = self.stack_frames.len();
        let mut frames = Vec::with_capacity(n + 1);
        for d in 0..=n {
            let (rust_ip, symbol) = if d == n {
                (self.ip, self.current_symbol.clone())
            } else {
                (
                    self.stack_frames[d].ret_ptr,
                    self.stack_frames[d].ret_symbol.clone(),
                )
            };
            let (closure, stack_start, arg_count) = if d == 0 {
                (root_closure_json(), 0, 0)
            } else {
                let frame = &self.stack_frames[d - 1];
                let arg_count = match &frame.closure.callable {
                    Callable::Local(lc) => lc.stack_arg_count,
                    Callable::Stl(_) => 0,
                };
                (
                    closure_to_json(&frame.closure, registry, header_len),
                    frame.stack_start,
                    arg_count,
                )
            };
            frames.push(CallFrameJson {
                closure,
                ip: self.node_ip(rust_ip, &symbol),
                chunk: chunk_str(&symbol),
                stack_start,
                arg_count,
            });
        }
        Ok(frames)
    }

    /// Our `ip` is body-relative; the reference's per-frame `ip` indexes the full bytecode array
    /// (header included) for the root chunk. Module chunks (STL bodies) carry no header.
    fn node_ip(&self, rust_ip: usize, symbol: &Option<Symbol>) -> usize {
        rust_ip
            + if symbol.is_none() {
                self.context.program_header_len()
            } else {
                0
            }
    }

    fn rust_ip(node_ip: usize, chunk: &str, context: &ExecutionContext) -> usize {
        node_ip.saturating_sub(if chunk == "root" {
            context.program_header_len()
        } else {
            0
        })
    }

    /// Rebuild a VM from a [`VmSnapshot`] against `context`. Inverse of [`Self::snapshot`]: cells are
    /// created empty first so closure captures resolve by id, containers are re-emplaced onto a fresh
    /// heap, and the open-upvalue list is reconstructed from the still-open cells.
    pub fn restore(
        context: &'a ExecutionContext,
        snapshot: &VmSnapshot,
    ) -> Result<HogVM<'a>, VmError> {
        let mut vm = HogVM::new(context)?;
        let header_len = context.program_header_len();

        let cells = rebuild_cells(&snapshot.upvalues, &mut vm.heap, header_len)?;

        let mut stack = Vec::with_capacity(snapshot.stack.len());
        for value in &snapshot.stack {
            stack.push(value_from_json(value, &mut vm.heap, &cells, header_len)?);
        }

        // Inverse of `build_call_stack`: the reference callStack has N+1 frames (root + N); we keep N
        // frames plus the live ip/symbol. Frame i bundles depth-i's return point (callStack[i]'s
        // ip/chunk) with depth-(i+1)'s closure and stack window.
        let call_stack = &snapshot.call_stack;
        let Some(active) = call_stack.last() else {
            return Err(VmError::Other("snapshot callStack is empty".to_string()));
        };
        vm.ip = Self::rust_ip(active.ip, &active.chunk, context);
        vm.current_symbol = chunk_to_symbol(&active.chunk);

        let n = call_stack.len() - 1;
        let mut stack_frames = Vec::with_capacity(n);
        for i in 0..n {
            stack_frames.push(CallFrame {
                ret_ptr: Self::rust_ip(call_stack[i].ip, &call_stack[i].chunk, context),
                ret_symbol: chunk_to_symbol(&call_stack[i].chunk),
                stack_start: call_stack[i + 1].stack_start,
                closure: closure_from_json(&call_stack[i + 1].closure, &cells, header_len)?,
            });
        }

        let mut throw_frames = Vec::with_capacity(snapshot.throw_stack.len());
        for t in &snapshot.throw_stack {
            // callStackLen counts reference frames (root + our depth); recover our depth and the
            // chunk that depth ran in so we can restore catch_symbol.
            let call_depth = t.call_stack_len.saturating_sub(1);
            let chunk = call_stack
                .get(call_depth)
                .map(|f| f.chunk.as_str())
                .unwrap_or("root");
            throw_frames.push(ThrowFrame {
                catch_ptr: Self::rust_ip(t.catch_ip, chunk, context),
                catch_symbol: chunk_to_symbol(chunk),
                stack_start: t.stack_len,
                call_depth,
            });
        }

        let open_upvalues = cells
            .values()
            .filter(|c| !c.borrow().closed)
            .cloned()
            .collect();

        vm.stack = stack;
        vm.stack_frames = stack_frames;
        vm.throw_frames = throw_frames;
        vm.open_upvalues = open_upvalues;
        vm.async_steps = snapshot.async_steps;
        vm.ops = snapshot.ops;
        // Carry the recorded high-water mark across resume — rebuilding the heap only accounts for
        // live values, so without this a restore→snapshot round-trip would lose the original peak.
        vm.heap.peak_bytes = vm.heap.peak_bytes.max(snapshot.max_mem_used);
        // Carry the trace across resume so a multi-suspension run accumulates one continuous trace.
        vm.telemetry = snapshot.telemetry.clone().unwrap_or_default();
        Ok(vm)
    }
}

// Helper function to simply run a program until it either finishes or returns an error
pub fn sync_execute(context: &ExecutionContext, print_debug: bool) -> Result<JsonValue, VmFailure> {
    let fail = |e, vm: Option<&HogVM>, step: usize| VmFailure {
        error: e,
        ip: vm.map_or(0, |vm| vm.ip),
        stack: vm.map_or(Vec::new(), |vm| vm.stack.clone()),
        step,
    };

    let mut vm = HogVM::new(context).map_err(|e| fail(e, None, 0))?;

    let mut i = 0;
    while i < context.max_steps {
        let res = if print_debug {
            vm.debug_step(&|s| println!("{s}"))
                .map_err(|e| fail(e, Some(&vm), i))?
        } else {
            vm.step().map_err(|e| fail(e, Some(&vm), i))?
        };

        match res {
            StepOutcome::Continue => {}
            StepOutcome::Finished(res) => return Ok(res),
            StepOutcome::NativeCall(name, args) => {
                // Sync execution can't suspend: an async function name isn't a registered native, so
                // this surfaces as an `UnknownFunction` error here — the correct outcome for a sync
                // consumer that hits an async call. Resumable execution handles it via [`resume`].
                match context.execute_native_function_call(&mut vm, &name, args) {
                    Ok(_) => {}
                    Err(err) => return Err(fail(err, Some(&vm), i)),
                };
            }
        }
        i += 1;
    }

    let err = VmError::OutOfResource("steps".to_string());

    Err(fail(err, Some(&vm), i))
}

/// Drive a fresh program to completion or its first async suspension — the resumable counterpart to
/// [`sync_execute`]. On a registered async call it returns [`Resumable::Suspended`] with a
/// serializable snapshot; the host performs the side effect and calls [`resume`].
pub fn execute_resumable(context: &ExecutionContext) -> Result<Resumable, VmFailure> {
    let vm = HogVM::new(context).map_err(|e| failure(e, None, 0))?;
    drive_resumable(vm, context)
}

/// Resume a snapshot with the result of the async function it suspended on. The result is pushed as
/// the value the suspended `CALL_GLOBAL` yields, and execution continues from where it left off.
pub fn resume(
    context: &ExecutionContext,
    state: &VmSnapshot,
    async_result: JsonValue,
) -> Result<Resumable, VmFailure> {
    let mut vm = HogVM::restore(context, state).map_err(|e| failure(e, None, 0))?;
    let value = vm
        .json_to_hog(&async_result)
        .map_err(|e| failure(e, Some(&vm), 0))?;
    vm.push_stack(value).map_err(|e| failure(e, Some(&vm), 0))?;
    drive_resumable(vm, context)
}

fn drive_resumable(mut vm: HogVM, context: &ExecutionContext) -> Result<Resumable, VmFailure> {
    let mut i = 0;
    while i < context.max_steps {
        let res = vm.step().map_err(|e| failure(e, Some(&vm), i))?;
        match res {
            StepOutcome::Continue => {}
            StepOutcome::Finished(result) => return Ok(Resumable::Finished(result)),
            StepOutcome::NativeCall(name, args) => {
                // A registered async function suspends instead of running inline: snapshot the state
                // (args already popped, `ip` past the call) and hand it back for the host to perform
                // the side effect and `resume`. Everything else is a normal inline native call.
                if context.is_async(&name) {
                    if vm.async_steps >= context.max_async_steps {
                        return Err(failure(
                            VmError::OutOfResource(format!(
                                "async steps ({})",
                                context.max_async_steps
                            )),
                            Some(&vm),
                            i,
                        ));
                    }
                    vm.async_steps += 1;
                    let mut json_args = Vec::with_capacity(args.len());
                    for arg in &args {
                        json_args.push(vm.hog_to_json(arg).map_err(|e| failure(e, Some(&vm), i))?);
                    }
                    let state = vm.snapshot().map_err(|e| failure(e, Some(&vm), i))?;
                    return Ok(Resumable::Suspended {
                        function: name,
                        args: json_args,
                        state: Box::new(state),
                    });
                }
                context
                    .execute_native_function_call(&mut vm, &name, args)
                    .map_err(|e| failure(e, Some(&vm), i))?;
            }
        }
        i += 1;
    }
    Err(failure(
        VmError::OutOfResource("steps".to_string()),
        Some(&vm),
        i,
    ))
}

fn failure(error: VmError, vm: Option<&HogVM>, step: usize) -> VmFailure {
    VmFailure {
        error,
        ip: vm.map_or(0, |vm| vm.ip),
        stack: vm.map_or(Vec::new(), |vm| vm.stack.clone()),
        step,
    }
}

/// The reference's telemetry opcode label: `"<num>/<SCREAMING_SNAKE_NAME>"` (e.g. `2/CALL_GLOBAL`).
fn op_telemetry_name(op: &Operation) -> String {
    let pascal = format!("{op:?}");
    let mut name = String::with_capacity(pascal.len() + 4);
    for (i, c) in pascal.char_indices() {
        if c.is_ascii_uppercase() && i != 0 {
            name.push('_');
        }
        name.push(c.to_ascii_uppercase());
    }
    format!("{}/{}", op.clone() as u8, name)
}

fn next_type_name(next: &JsonValue) -> String {
    match next {
        JsonValue::Null => "null".to_string(),
        JsonValue::Bool(_) => "bool".to_string(),
        JsonValue::Number(_) => "number".to_string(),
        JsonValue::String(_) => "string".to_string(),
        JsonValue::Array(_) => "array".to_string(),
        JsonValue::Object(_) => "object".to_string(),
    }
}
