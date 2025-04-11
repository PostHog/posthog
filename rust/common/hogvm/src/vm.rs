use std::{any::Any, cmp::min, collections::HashMap};

use serde::de::DeserializeOwned;
use serde_json::{Number, Value as JsonValue};

use crate::{
    error::VmError,
    memory::{HeapReference, VmHeap},
    ops::Operation,
    stl::{stl, NativeFunction},
    util::{like, regex_match},
    values::{Callable, Closure, FromHogLiteral, HogLiteral, HogValue, LocalCallable, Num, NumOp},
};

pub struct ExecutionContext<'a> {
    pub bytecode: &'a [JsonValue],
    pub globals: HashMap<String, HogValue>,
    pub max_stack_depth: usize,
}

#[derive(Debug, Clone)]
pub enum StepOutcome {
    Finished(HogLiteral),
    NativeCall(String, Vec<HogValue>),
    Continue,
}

pub struct CallFrame {
    pub ret_ptr: usize,               // Where to jump back to when we're done
    pub stack_start: usize,           // Point in the stack the frame values start
    pub captures: Vec<HeapReference>, // Values captured from the parent scope/frame
}

pub struct ThrowFrame {
    pub catch_ptr: usize,   // The ptr to jump to if we throw
    pub stack_start: usize, // The stack size when we entered the try
    pub call_depth: usize,  // The depth of the call stack when we entered the try
}

pub struct VmState<'a> {
    pub stack: Vec<HogValue>,
    pub heap: VmHeap,

    pub stack_frames: Vec<CallFrame>,
    pub throw_frames: Vec<ThrowFrame>,
    pub ip: usize,

    pub context: &'a ExecutionContext<'a>,
    pub version: usize,
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

impl<'a> VmState<'a> {
    pub fn new(context: &'a ExecutionContext<'a>) -> Result<Self, VmError> {
        if context.bytecode.len() < 1 {
            return Err(VmError::InvalidBytecode(
                "Missing bytecode marker at position 0".to_string(),
            ));
        }

        let mut ip = 1; // Skip the bytecode marker
        let bytecode_marker = context.bytecode[0].clone();

        let version = match bytecode_marker {
            JsonValue::String(s) if s == "_H" => {
                let version = context.bytecode.get(1).cloned();
                if version.is_some() {
                    ip += 1; // Skip the version marker
                }
                let version = version.unwrap_or(JsonValue::Number(Number::from(0)));
                match version {
                    JsonValue::Number(n) => n.as_u64().ok_or(VmError::InvalidBytecode(
                        "Invalid version number".to_string(),
                    ))?,
                    _ => {
                        return Err(VmError::InvalidBytecode(
                            "Invalid version number".to_string(),
                        ))
                    }
                }
            }
            _ => {
                return Err(VmError::InvalidBytecode(format!(
                    "Invalid bytecode marker: {:?}",
                    bytecode_marker
                )))
            }
        };

        Ok(Self {
            stack: Vec::new(),
            stack_frames: Vec::new(),
            throw_frames: Vec::new(),
            ip,
            context,
            heap: Default::default(),
            version: version as usize,
        })
    }

    // Returns the first stack item in this call frames scope
    fn current_frame_base(&self) -> usize {
        if self.stack_frames.is_empty() {
            0
        } else {
            self.stack_frames[self.stack_frames.len() - 1].stack_start
        }
    }

    // Returns a ptr to the captured value in this frames scope, if there is one,
    // or an error if the index is out of bounds
    fn get_capture(&self, index: usize) -> Result<HeapReference, VmError> {
        let Some(frame) = self.stack_frames.last() else {
            return Err(VmError::NoFrame);
        };
        frame
            .captures
            .get(index)
            .cloned()
            .ok_or(VmError::CaptureOutOfBounds(index))
    }

    fn next<'s, T>(&'s mut self) -> Result<T, VmError>
    where
        T: DeserializeOwned + Any,
    {
        let Some(next) = self.context.bytecode.get(self.ip) else {
            return Err(VmError::EndOfProgram(self.ip));
        };

        self.ip += 1;

        let next_type_name = next_type_name(next);
        let expected = std::any::type_name::<T>();

        serde_json::from_value(next.clone())
            .map_err(|_| VmError::InvalidValue(next_type_name, expected.to_string()))
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

    // Move a value from the stack onto the heap, replacing it with a reference to the heap value,
    // and returning a reference to it. If it was already a reference, return it.
    fn hoist(&mut self, idx: usize) -> Result<HeapReference, VmError> {
        let item = self.clone_stack_item(idx)?;
        match item {
            HogValue::Lit(lit) => {
                let ptr = self.heap.emplace(HogValue::Lit(lit))?;
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
        self.stack.truncate(new_len);
        Ok(())
    }

    fn push_stack(&mut self, value: impl Into<HogValue>) -> Result<(), VmError> {
        if self.stack.len() >= self.context.max_stack_depth {
            return Err(VmError::StackOverflow);
        }
        self.stack.push(value.into());
        Ok(())
    }

    // TODO - this is how function calls are constructed - you construct a function
    // reference, push it onto the stack, and then call it
    fn get_fn_reference(&self, _chain: &[String]) -> Result<HogLiteral, VmError> {
        return Err(VmError::NotImplemented("imports".to_string()));
    }

    fn clone_stack_item(&self, idx: usize) -> Result<HogValue, VmError> {
        self.stack.get(idx).cloned().ok_or(VmError::StackUnderflow)
    }

    fn prep_native_call(&self, name: String, args: Vec<HogValue>) -> StepOutcome {
        return StepOutcome::NativeCall(name, args);
    }

    // TODO - should use Write trait
    pub fn debug_step(&mut self, output: &dyn Fn(String)) -> Result<StepOutcome, VmError> {
        let op: Operation = self.next()?;
        self.ip -= 1;
        output(format!(
            "Op ({}): {:?} [{:?}], Stack: {:?}",
            self.ip,
            op,
            &self.context.bytecode
                [self.ip.saturating_sub(1)..min(self.ip + 2, self.context.bytecode.len())],
            self.stack
        ));
        self.step()
    }

    pub fn step(&mut self) -> Result<StepOutcome, VmError> {
        let op: Operation = self.next()?;

        match op {
            Operation::GetGlobal => {
                // GetGlobal is used to do 1 of 2 things, either push a value from a global variable onto the stack, or push a new
                // function reference (referred to in other impls as a "closure") onto the stack - either a native one, or a hog one
                let mut chain: Vec<String> = Vec::new();
                let count: usize = self.next()?;
                for _ in 0..count {
                    chain.push(self.pop_stack_as()?);
                }
                if let Some(chain_start) = self.context.globals.get(&chain[0]) {
                    // TODO - this is a lot more strict that other

                    let rest_of_chain: Vec<HogValue> = chain
                        .into_iter()
                        .skip(1)
                        .map(HogLiteral::from)
                        .map(HogValue::from)
                        .collect();

                    self.push_stack(
                        chain_start
                            .get_nested(&rest_of_chain, &self.heap)?
                            .ok_or(VmError::UnknownGlobal(format!(
                                "{:?}.{:?}",
                                chain_start, rest_of_chain
                            )))?
                            .clone(),
                    )?;
                } else if let Ok(closure) = self.get_fn_reference(&chain) {
                    self.push_stack(closure)?;
                } else {
                    return Err(VmError::UnknownGlobal(chain.join(".")));
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
                let mut args = Vec::with_capacity(arg_count);
                for _ in 0..arg_count {
                    args.push(self.pop_stack()?);
                }
                if self.version == 0 {
                    // In v0, the arguments were expected to be passed in
                    // stack push order, not pop order. We simulate that here
                    // but always popping, but then maybe reversing
                    args.reverse();
                }
                // This VM does native calls like so: it returns a "native call" struct,
                // which the executing environment can use to execute the native call.
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
                let val = self.pop_stack_as::<bool>()?;
                // TODO - technically, we could assert here that this push will always succeed,
                // and it'd let us skip a bounds check I /think/, but lets not go microoptimizing yet
                self.push_stack(HogLiteral::from(!val))?;
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
                self.push_stack(a.equals(&b, &self.heap)?)?;
            }
            Operation::NotEq => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.not_equals(&b, &self.heap)?)?;
            }
            Operation::Gt => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Gt, &a, &b)?)?;
            }
            Operation::GtEq => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Gte, &a, &b)?)?;
            }
            Operation::Lt => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Lt, &a, &b)?)?;
            }
            Operation::LtEq => {
                let (a, b) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(Num::binary_op(NumOp::Lte, &a, &b)?)?;
            }
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
            Operation::Regex => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(regex_match(val, pat, true)?)?;
            }
            Operation::NotRegex => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(!regex_match(val, pat, true)?)?;
            }
            Operation::Iregex => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(regex_match(val, pat, false)?)?;
            }
            Operation::NotIregex => {
                let (val, pat): (String, String) = (self.pop_stack_as()?, self.pop_stack_as()?);
                self.push_stack(!regex_match(val, pat, false)?)?;
            }
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
            Operation::Integer => {
                let val: i64 = self.next()?;
                self.push_stack(val)?;
            }
            Operation::Float => {
                let val: f64 = self.next()?;
                self.push_stack(val)?;
            }
            Operation::Pop => {
                self.pop_stack()?;
            }
            Operation::GetLocal => {
                let base = self.current_frame_base();
                let offset: usize = self.next()?;
                let ptr = self.hoist(base + offset)?;
                self.push_stack(ptr)?;
            }
            Operation::SetLocal => {
                // Replace some item "lower" in the stack with the top one.
                let base = self.current_frame_base();
                let offset: usize = self.next()?;
                let value = self.pop_stack()?;
                self.set_stack_val(base + offset, value)?;
            }
            Operation::Return => {
                let result = self.pop_stack()?;
                let last_frame = self.stack_frames.pop();
                let Some(frame) = last_frame else {
                    return Ok(StepOutcome::Finished(result.deref(&self.heap)?.clone()));
                };

                if self.stack_frames.is_empty() {
                    return Ok(StepOutcome::Finished(result.deref(&self.heap)?.clone()));
                };

                self.truncate_stack(frame.stack_start)?;
                self.ip = frame.ret_ptr;
                self.push_stack(result)?;
            }
            Operation::Jump => {
                let offset: usize = self.next()?;
                self.ip += offset;
            }
            Operation::JumpIfFalse => {
                let offset: usize = self.next()?;
                if !self.pop_stack_as::<bool>()? {
                    self.ip += offset;
                }
            }
            Operation::JumpIfStackNotNull => {
                let offset: usize = self.next()?;
                // Weirdly, this operation doesn't pop the value from the stack. This is mostly a random choice.
                if !self.stack.is_empty() {
                    let item = self.clone_stack_item(self.stack.len() - 1)?;
                    let item = item.deref(&self.heap)?;
                    if matches!(item, HogLiteral::Null) {
                        self.ip += offset;
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
                let map: HashMap<String, HogValue> =
                    HashMap::from_iter(keys.into_iter().zip(values.into_iter()));
                self.push_stack(HogLiteral::Object(map))?;
            }
            Operation::Array => {
                let element_count: usize = self.next()?;
                let mut elements = Vec::with_capacity(element_count);
                for _ in 0..element_count {
                    elements.push(self.pop_stack()?);
                }
                // We've walked back down the stack, but the compiler expects the array to be in pushed order
                elements.reverse();
                self.push_stack(HogLiteral::Array(elements))?;
            }
            Operation::Tuple => {
                // The compiler has special case handling for tuples, but the typescript VM doesn't, so neither do we,
                // this is effectively Array
                let element_count: usize = self.next()?;
                let mut elements = Vec::with_capacity(element_count);
                for _ in 0..element_count {
                    elements.push(self.pop_stack()?);
                }
                // We've walked back down the stack, but the compiler expects the "tuple" to be in pushed order
                elements.reverse();
                self.push_stack(HogLiteral::Array(elements))?;
            }
            Operation::GetProperty => {
                let needle = self.pop_stack()?;
                let haystack = self.pop_stack()?;
                let chain = [needle];
                let Some(res) = haystack.get_nested(&chain, &self.heap)? else {
                    return Err(VmError::UnknownProperty(format!("{:?}", chain[0])));
                };
                self.push_stack(res.clone())?;
            }
            Operation::GetPropertyNullish => {
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
                    HogValue::Ref(ptr) => self.heap.deref_mut(*ptr)?,
                    HogValue::Lit(_) => {
                        // TODO - this is a divergence from the original implementation - basically, if the target you've specified isn't on the heap,
                        // we'll drop it immediately after setting the property, which is a no-op. This should never happen - we should be using GET_LOCAL
                        // to hoist properties onto the heap before calling SET_PROPERTY, I /think/, but I'm not certain. I might end up making all
                        // objects be auto-allocated on the heap, just to be certain we're never hit this case for anything set_property() would succeed for
                        return Err(VmError::ExpectedObject);
                    }
                };

                target.set_property(key, val)?;
            }
            Operation::Try => {
                let catch_offset: usize = self.next()?;
                let catch_ip = self.ip + catch_offset + 1; // +1 to skip the POP_TRY that follows the try'd operations
                let frame = ThrowFrame {
                    catch_ptr: catch_ip,
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
                }
                .into();
                self.push_stack(HogLiteral::Callable(callable.into()))?;
                self.ip += body_length;
            }
            // A closure is a callable, plus some captured arguments from the scope
            // it was constructed in.
            Operation::Closure => {
                let callable: Callable = self.pop_stack_as()?;
                let capture_count: usize = self.next()?;
                // Irrefutable match for now
                let Callable::Local(unwrapped) = &callable;
                // Because captures are an implicit part of compilation, it's never valid
                // for them to be different from the number of captures in the callable.
                if capture_count != unwrapped.capture_count {
                    return Err(VmError::InvalidCall(
                        "invalid number of heap arguments".to_string(),
                    ));
                }
                let mut captures = Vec::with_capacity(capture_count);
                for _ in 0..capture_count {
                    // Indicates whether this captured argument is to a stack variable in this
                    // frames stack, or a captured argument in this frames captured arguments list
                    let is_local: bool = self.next()?;
                    let offset: usize = self.next()?;
                    if is_local {
                        let index = self.current_frame_base() + offset;
                        captures.push(self.hoist(index)?);
                    } else {
                        captures.push(self.get_capture(offset)?);
                    }
                }

                let closure = Closure { callable, captures };
                self.push_stack(HogLiteral::Closure(closure))?;
            }
            Operation::CallLocal => {
                let closure: Closure = self.pop_stack_as()?;
                let arg_count: usize = self.next()?;
                let Callable::Local(callable) = &closure.callable;
                if arg_count > callable.stack_arg_count {
                    return Err(VmError::InvalidCall(format!(
                        "Too many args - expected {}, got {}",
                        callable.stack_arg_count, arg_count
                    )));
                }
                let null_args = callable.stack_arg_count - arg_count;
                // For pure-hog function calls (calls to "local" callables), we just push a null onto the stack for each missing argument,
                // then construct the stack frame, and jump to the callable's frame ip. For other kinds of calls (which we don't support yet),
                // we'll have to do something more complicated
                for _ in 0..null_args {
                    self.push_stack(HogLiteral::Null)?;
                }
                let frame = CallFrame {
                    ret_ptr: self.ip,
                    stack_start: self.stack.len() - callable.stack_arg_count,
                    captures: closure.captures,
                };
                self.stack_frames.push(frame);
                self.ip = callable.ip; // Do the jump
            }
            Operation::GetUpvalue => {
                let index: usize = self.next()?;
                let ptr = self.get_capture(index)?;
                self.push_stack(ptr)?;
            }
            Operation::SetUpvalue => {
                let index: usize = self.next()?;
                let ptr = self.get_capture(index)?;
                *self.heap.get_mut(ptr)? = self.pop_stack()?;
            }
            Operation::CloseUpvalue => {
                // The TS impl just pops here - I don't really understand why
                self.pop_stack()?;
            }
        }

        Ok(StepOutcome::Continue)
    }
}

#[derive(Debug, Clone)]
pub struct VmFailure {
    pub error: VmError,
    pub ip: usize,
    pub stack: Vec<HogValue>,
    pub step: usize,
}

pub fn sync_execute(
    bytecode: &[JsonValue],
    max_steps: usize,
    stl_extensions: HashMap<String, NativeFunction>,
    debug: bool,
) -> Result<HogLiteral, VmFailure> {
    let context = ExecutionContext {
        bytecode,
        globals: HashMap::new(),
        max_stack_depth: 1024,
    };

    let mut native_fns: HashMap<String, NativeFunction> =
        stl().iter().map(|(a, b)| (a.to_string(), *b)).collect();

    native_fns.extend(stl_extensions);

    let fail = |e, vm: Option<&VmState>, step: usize| VmFailure {
        error: e,
        ip: vm.map_or(0, |vm| vm.ip),
        stack: vm.map_or(Vec::new(), |vm| vm.stack.clone()),
        step,
    };

    let mut vm = VmState::new(&context).map_err(|e| fail(e, None, 0))?;

    let mut i = 0;
    while i < max_steps {
        let res = if debug {
            vm.debug_step(&|s| println!("{}", s))
                .map_err(|e| fail(e, Some(&vm), i))?
        } else {
            vm.step().map_err(|e| fail(e, Some(&vm), i))?
        };

        match res {
            StepOutcome::Continue => {
                i += 1;
            }
            StepOutcome::Finished(res) => return Ok(res),
            StepOutcome::NativeCall(name, args) => {
                let Some(native_fn) = native_fns.get(&name) else {
                    return Err(fail(VmError::UnknownFunction(name), Some(&vm), i));
                };
                let result = native_fn(&vm, args);
                match result {
                    Ok(value) => vm.push_stack(value).map_err(|e| fail(e, Some(&vm), i))?,
                    Err(err) => return Err(fail(err, Some(&vm), i)),
                };
            }
        }
        i += 1;
    }

    let err = VmError::OutOfResource("steps".to_string());

    return Err(fail(err, Some(&vm), i));
}
