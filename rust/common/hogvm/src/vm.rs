use std::{any::Any, collections::HashMap};

use serde::de::DeserializeOwned;
use serde_json::Value as JsonValue;

use crate::{
    error::{Error, VmError},
    ops::Operation,
    util::{like, regex_match},
    values::{Callable, FromHogValue, HogValue, Num, NumOp},
};

pub struct ExecutionContext<'a> {
    bytecode: &'a [JsonValue],
    globals: HashMap<String, HogValue>,
    max_stack_depth: usize,
}

#[derive(Debug, Clone)]
pub struct HeapValue {
    epoch: usize,
    value: HogValue,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct HeapReference {
    idx: usize,
    epoch: usize, // Used to allow heap values to be freed, and their
}

#[derive(Default)]
pub struct VmHeap {
    inner: Vec<HeapValue>,
    freed: Vec<HeapReference>, // Indices of freed heap values, for reuse
}

#[derive(Debug, Clone, PartialEq)]
pub enum StackItem {
    Value(HogValue),
    Reference(HeapReference),
}

impl VmHeap {
    pub fn alloc(&mut self, value: HogValue) -> Result<HeapReference, VmError> {
        let (next_idx, next_epoch) = match self.freed.pop() {
            Some(ptr) => (ptr.idx, ptr.epoch + 1),
            None => (self.inner.len(), 0),
        };

        if self.inner.len() <= next_idx {
            self.inner.push(HeapValue {
                epoch: next_epoch,
                value,
            });
        } else {
            self.inner[next_idx] = HeapValue {
                epoch: next_epoch,
                value,
            };
        }

        Ok(HeapReference {
            idx: next_idx,
            epoch: next_epoch,
        })
    }

    pub fn free(&mut self, ptr: HeapReference) -> Result<(), VmError> {
        if self.inner.len() < ptr.idx {
            return Err(VmError::HeapIndexOutOfBounds);
        }

        let to_free = &mut self.inner[ptr.idx];

        if to_free.epoch != ptr.epoch {
            return Err(VmError::UseAfterFree);
        }

        // All existing references to this value are now invalid, and any use of them will result in a UseAfterFree error.
        to_free.epoch += 1;
        to_free.value = HogValue::Null;

        // This slot's now available for reuse.
        self.freed.push(ptr);
        Ok(())
    }

    pub fn load(&mut self, ptr: HeapReference) -> Result<HogValue, VmError> {
        if self.inner.len() < ptr.idx {
            return Err(VmError::HeapIndexOutOfBounds);
        }

        let to_load = &mut self.inner[ptr.idx];

        if to_load.epoch != ptr.epoch {
            return Err(VmError::UseAfterFree);
        }

        // TODO - this is a bit inefficient, but allows us to track heap memory usage by forcing callers to call
        // `store` to update the value.
        Ok(to_load.value.clone())
    }

    pub fn store(&mut self, ptr: HeapReference, value: HogValue) -> Result<(), VmError> {
        if self.inner.len() < ptr.idx {
            return Err(VmError::HeapIndexOutOfBounds);
        }

        let to_store = &mut self.inner[ptr.idx];

        if to_store.epoch != ptr.epoch {
            return Err(VmError::UseAfterFree);
        }

        to_store.value = value;
        Ok(())
    }
}

pub struct ExecOutcome {
    pub returned: Option<HogValue>, // If Some, we're finished executing the program
}

pub struct CallFrame {
    ret_ptr: usize,     // Where to jump back to when we're done
    stack_start: usize, // Point in the stack the frame values start
}

pub struct ThrowFrame {
    catch_ptr: usize,   // The ptr to jump to if we throw
    stack_start: usize, // The stack size when we entered the try
    call_depth: usize,  // The depth of the call stack when we entered the try
}

pub struct VmState<'a> {
    stack: Vec<StackItem>,
    heap: VmHeap,

    stack_frames: Vec<CallFrame>,
    throw_frames: Vec<ThrowFrame>,
    ip: usize,

    context: &'a ExecutionContext<'a>,
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
    pub fn new(context: &'a ExecutionContext<'a>) -> Self {
        Self {
            stack: Vec::new(),
            stack_frames: Vec::new(),
            throw_frames: Vec::new(),
            ip: 0,
            context,
            heap: Default::default(),
        }
    }

    fn current_frame_base(&self) -> usize {
        if self.stack_frames.is_empty() {
            0
        } else {
            self.stack_frames[self.stack_frames.len() - 1].stack_start
        }
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

    fn peek<'s, T>(&'s mut self) -> Result<T, VmError>
    where
        T: DeserializeOwned + Any,
    {
        let res = self.next();
        self.ip -= 1;
        res
    }

    fn pop_stack(&mut self) -> Result<HogValue, VmError> {
        if self.stack.len() <= self.current_frame_base() {
            return Err(VmError::StackUnderflow);
        }
        let item = self.stack.pop().ok_or(VmError::StackUnderflow)?;

        match item {
            StackItem::Value(hog_value) => Ok(hog_value),
            StackItem::Reference(reference) => self.heap.load(reference),
        }
    }

    fn try_pop_as<T>(&mut self) -> Result<T, VmError>
    where
        T: FromHogValue,
    {
        self.pop_stack().and_then(HogValue::try_into)
    }

    fn set_stack_val(&mut self, idx: usize, value: HogValue) -> Result<(), VmError> {
        self.stack
            .get_mut(idx)
            .ok_or(VmError::StackIndexOutOfBounds)
            .map(|v| *v = value)
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
    fn get_fn_reference(&self, _chain: &[String]) -> Result<HogValue, VmError> {
        return Err(VmError::NotImplemented("imports".to_string()));
    }

    pub fn step(&mut self) -> Result<ExecOutcome, VmError> {
        let op: Operation = self.next()?;

        match op {
            Operation::GetGlobal => {
                // GetGlobal is used to do 1 of 2 things, either push a value from a global variable onto the stack, or push a new
                // function reference (referred to in other impls as a "closure") onto the stack - either a native one, or a hog one
                let mut chain: Vec<String> = Vec::new();
                let count: usize = self.next()?;
                for _ in 0..count {
                    chain.push(self.try_pop_as()?);
                }
                if let Some(chain_start) = self.context.globals.get(&chain[0]) {
                    // TODO - this is a lot more strict that other implementations
                    self.push_stack(
                        chain_start
                            .get_nested(&chain[1..])
                            .ok_or(VmError::UnknownGlobal(chain.join(".")))?
                            .clone(),
                    )?;
                } else if let Ok(closure) = self.get_fn_reference(&chain) {
                    self.push_stack(closure)?;
                } else {
                    return Err(VmError::UnknownGlobal(chain.join(".")));
                }
            }
            Operation::CallGlobal => return Err(VmError::NotImplemented("CallGlobal".to_string())),
            Operation::And => {
                let count: usize = self.next()?;
                let mut acc: HogValue = true.into();
                for _ in 0..count {
                    let value = self.pop_stack()?;
                    acc = acc.and(&value)?;
                }
                self.push_stack(acc)?;
            }
            Operation::Or => {
                let count: usize = self.next()?;
                let mut acc: HogValue = false.into();
                for _ in 0..count {
                    let value = self.pop_stack()?;
                    acc = acc.or(&value)?;
                }
                self.push_stack(acc)?;
            }
            Operation::Not => {
                let val = self.pop_stack()?;
                let val = val.try_as::<bool>()?;
                // TODO - technically, we could assert here that this push will always succeed,
                // and it'd let us skip a bounds check I /think/, but lets not go microoptimizing yet
                self.push_stack(!val)?;
            }
            Operation::Plus => {
                let (a, b) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(Num::binary_op(NumOp::Add, &a, &b)?)?;
            }
            Operation::Minus => {
                let (a, b) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(Num::binary_op(NumOp::Sub, &a, &b)?)?;
            }
            Operation::Mult => {
                let (a, b) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(Num::binary_op(NumOp::Mul, &a, &b)?)?;
            }
            Operation::Div => {
                let (a, b) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(Num::binary_op(NumOp::Div, &a, &b)?)?;
            }
            Operation::Mod => {
                let (a, b) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(Num::binary_op(NumOp::Mod, &a, &b)?)?;
            }
            Operation::Eq => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.equals(&b)?)?;
            }
            Operation::NotEq => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.not_equals(&b)?)?;
            }
            Operation::Gt => {
                let (a, b) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(Num::binary_op(NumOp::Gt, &a, &b)?)?;
            }
            Operation::GtEq => {
                let (a, b) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(Num::binary_op(NumOp::Gte, &a, &b)?)?;
            }
            Operation::Lt => {
                let (a, b) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(Num::binary_op(NumOp::Lt, &a, &b)?)?;
            }
            Operation::LtEq => {
                let (a, b) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(Num::binary_op(NumOp::Lte, &a, &b)?)?;
            }
            Operation::Like => {
                let (val, pat): (String, String) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(like(val, pat, true)?)?;
            }
            Operation::Ilike => {
                let (val, pat): (String, String) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(like(val, pat, false)?)?;
            }
            Operation::NotLike => {
                let (val, pat): (String, String) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(!like(val, pat, true)?)?;
            }
            Operation::NotIlike => {
                let (val, pat): (String, String) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(!like(val, pat, false)?)?;
            }
            Operation::In => {
                let (needle, haystack) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(haystack.contains(&needle)?)?;
            }
            Operation::NotIn => {
                let (needle, haystack) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(haystack.contains(&needle)?.not()?)?;
            }
            Operation::Regex => {
                let (val, pat): (String, String) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(regex_match(val, pat, true)?)?;
            }
            Operation::NotRegex => {
                let (val, pat): (String, String) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(!regex_match(val, pat, true)?)?;
            }
            Operation::Iregex => {
                let (val, pat): (String, String) = (self.try_pop_as()?, self.try_pop_as()?);
                self.push_stack(regex_match(val, pat, false)?)?;
            }
            Operation::NotIregex => {
                let (val, pat): (String, String) = (self.try_pop_as()?, self.try_pop_as()?);
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
                self.push_stack(HogValue::Null)?;
            }
            Operation::String => {
                self.push_stack(String::new())?;
            }
            Operation::Integer => {
                self.push_stack(0)?;
            }
            Operation::Float => {
                self.push_stack(0.0)?;
            }
            Operation::Pop => {
                self.pop_stack()?;
            }
            Operation::GetLocal => {
                // Reaches "back" in the stack some number of items, and puts a reference to that on the top of the stack
                let base = self.current_frame_base();
                let offset: usize = self.next()?;
                self.push_stack(self.clone_stack_val(base + offset)?)?;
            }
            Operation::SetLocal => {
                // Sets some value "lower" in the stack
                let base = self.current_frame_base();
                let offset: usize = self.next()?;
                let value = self.pop_stack()?;
                self.set_stack_val(base + offset, value)?;
            }
            Operation::Return => {
                let result = self.pop_stack()?;
                let last_frame = self.stack_frames.pop();
                let Some(frame) = last_frame else {
                    return Ok(ExecOutcome {
                        returned: Some(result),
                    });
                };

                if self.stack_frames.is_empty() {
                    return Ok(ExecOutcome {
                        returned: Some(result),
                    });
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
                if !self.try_pop_as::<bool>()? {
                    self.ip += offset;
                }
            }
            Operation::JumpIfStackNotNull => {
                let offset: usize = self.next()?;
                // Weirdly, this operation doesn't pop the value from the stack, but is always followed by a pop,
                // based on the current compiler. I've asked marius why, and will update this comment once I have an answer.
                if !self.stack.is_empty()
                    && !matches!(self.clone_stack_val(self.stack.len())?, HogValue::Null)
                {
                    self.ip += offset;
                }
            }
            // We don't implement DeclareFn, because it's not used in the current compiler - it uses
            // "callables" constructed on the stack, which are then called by constructing a "closure",
            // which is basically a function call that wraps a "callable" and populates it's argument list
            Operation::DeclareFn => return Err(VmError::NotImplemented("DeclareFn".to_string())),
            Operation::Dict => {
                let element_count: usize = self.next()?;
                let mut keys = Vec::with_capacity(element_count);
                let mut values = Vec::with_capacity(element_count);
                // The keys and values are pushed into the stack in key:value, key:value pairs, but we're
                // going to walk the stack backwards to construct the dictionary
                for _ in 0..element_count {
                    values.push(self.pop_stack()?);
                    keys.push(self.try_pop_as::<String>()?);
                }
                let map: HashMap<String, HogValue> =
                    HashMap::from_iter(keys.into_iter().zip(values.into_iter()));
                self.push_stack(HogValue::Object(map))?;
            }
            Operation::Array => {
                let element_count: usize = self.next()?;
                let mut elements = Vec::with_capacity(element_count);
                for _ in 0..element_count {
                    elements.push(self.pop_stack()?);
                }
                // We've walked back down the stack, but the compiler expects the array to be in pushed order
                elements.reverse();
                self.push_stack(HogValue::Array(elements))?;
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
                self.push_stack(HogValue::Array(elements))?;
            }
            Operation::GetProperty => {
                let needle = self.try_pop_as::<String>()?;
                let haystack = self.pop_stack()?;
                let chain = [needle.as_str()];
                let Some(res) = haystack.get_nested(&chain) else {
                    return Err(VmError::UnknownProperty(needle));
                };
                self.push_stack(res.clone())?;
            }
            Operation::GetPropertyNullish => {
                let needle = self.try_pop_as::<String>()?;
                let haystack = self.pop_stack()?;
                let chain = [needle.as_str()];
                let res = haystack
                    .get_nested(&chain)
                    .cloned()
                    .unwrap_or(HogValue::Null);
                self.push_stack(res)?;
            }
            Operation::SetProperty => {
                // TODO - pretty sure this is, effectively, a no-op, since the dict's immediately dropped,
                // but nontheless, this is what the typescript VM does
                let val = self.pop_stack()?;
                let key = self.try_pop_as::<String>()?;
                let HogValue::Object(mut obj) = self.pop_stack()? else {
                    return Err(VmError::ExpectedObject);
                };
                obj.insert(key, val);
                // TODO this is the point at which I'd think we should push_stack, but existing impls don't, :shrug:
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
                let _type: Option<String> = exception
                    .get_nested(&["type"])
                    .cloned()
                    .and_then(|v| v.try_into().ok());
                let message: Option<String> = exception
                    .get_nested(&["message"])
                    .cloned()
                    .and_then(|v| v.try_into().ok());
                // The other impls here have some special case handling that treats "Error" as a distinct type, but
                // as far as I can tell, a "hog error" is just a HogValue::Object with some specific properties, so
                // I'll just check those exist. hog is mostly duck-typed, based on the existing impls
                if _type.is_none() || message.is_none() {
                    return Err(VmError::InvalidException);
                };

                let Some(frame) = self.throw_frames.pop() else {
                    let payload = exception
                        .get_nested(&["payload"])
                        .and_then(|val| match val {
                            HogValue::Object(obj) => Some(obj),
                            _ => None,
                        })
                        .cloned();
                    return Err(VmError::UncaughtException(
                        _type.unwrap(),
                        message.unwrap(),
                        payload,
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
                let heap_arg_count: usize = self.next()?;
                let body_length: usize = self.next()?;
                let callable = Callable::Local {
                    name: (name),
                    stack_arg_count: (stack_arg_count),
                    heap_arg_count: (heap_arg_count),
                    ip: (self.ip),
                };
                self.push_stack(HogValue::Callable(callable))?;
                self.ip += body_length;
            }
            Operation::Closure => {
                // A closure is just the actually invoke-able wrapper around a callable, that collects any stack and heap arguments
            }
            Operation::CallLocal => todo!(),
            Operation::GetUpvalue => todo!(),
            Operation::SetUpvalue => todo!(),
            Operation::CloseUpvalue => todo!(),
        }

        Ok(ExecOutcome { returned: None }) // Continue executing
    }
}

pub fn sync_execute(bytecode: &[JsonValue]) -> Result<(), Error> {
    let context = ExecutionContext {
        bytecode,
        globals: HashMap::new(),
        max_stack_depth: 1024,
    };

    let mut vm = VmState::new(&context);
    loop {
        vm.step()?;
    }
}
