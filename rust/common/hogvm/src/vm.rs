use std::{any::Any, collections::HashMap};

use serde::de::DeserializeOwned;
use serde_json::Value as JsonValue;

use crate::{
    error::{Error, VmError},
    ops::Operation,
    util::{like, regex_match},
    values::{FromHogValue, HogValue, Num, NumOp},
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

        self.freed.push(ptr);
        Ok(())
    }

    pub fn load(&mut self, ptr: HeapReference) -> Result<&mut HogValue, VmError> {
        if self.inner.len() < ptr.idx {
            return Err(VmError::HeapIndexOutOfBounds);
        }

        let to_load = &mut self.inner[ptr.idx];

        if to_load.epoch != ptr.epoch {
            return Err(VmError::UseAfterFree);
        }

        Ok(&mut to_load.value)
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

pub struct VmState<'a> {
    stack: Vec<HogValue>,
    heap: Vec<HeapValue>,
    stack_frames: Vec<usize>,
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
            ip: 0,
            context,
            heap: Default::default(),
        }
    }

    fn current_frame_base(&self) -> usize {
        if self.stack_frames.is_empty() {
            0
        } else {
            self.stack_frames[self.stack_frames.len() - 1]
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
            return Err(VmError::StackUnderflow(self.ip));
        }
        self.stack.pop().ok_or(VmError::StackUnderflow(self.ip))
    }

    fn try_pop_as<T>(&mut self) -> Result<T, VmError>
    where
        T: FromHogValue,
    {
        self.pop_stack().and_then(HogValue::try_into)
    }

    fn push_stack(&mut self, value: impl Into<HogValue>) -> Result<(), VmError> {
        if self.stack.len() >= self.context.max_stack_depth {
            return Err(VmError::StackOverflow(self.ip));
        }
        self.stack.push(value.into());
        Ok(())
    }

    // TODO - this is how function calls are constructed - you construct a function
    // reference, push it onto the stack, and then call it
    fn get_fn_reference(&self, _chain: &[String]) -> Result<HogValue, VmError> {
        return Err(VmError::NotImplemented("imports".to_string()));
    }

    pub fn step(&mut self) -> Result<Option<()>, VmError> {
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
            Operation::GetLocal => todo!(),
            Operation::SetLocal => todo!(),
            Operation::Return => todo!(),
            Operation::Jump => todo!(),
            Operation::JumpIfFalse => todo!(),
            Operation::DeclareFn => todo!(),
            Operation::Dict => todo!(),
            Operation::Array => todo!(),
            Operation::Tuple => todo!(),
            Operation::GetProperty => todo!(),
            Operation::SetProperty => todo!(),
            Operation::JumpIfStackNotNull => todo!(),
            Operation::GetPropertyNullish => todo!(),
            Operation::Throw => todo!(),
            Operation::Try => todo!(),
            Operation::PopTry => todo!(),
            Operation::Callable => todo!(),
            Operation::Closure => todo!(),
            Operation::CallLocal => todo!(),
            Operation::GetUpvalue => todo!(),
            Operation::SetUpvalue => todo!(),
            Operation::CloseUpvalue => todo!(),
        }

        Ok(None) // Continue executing
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
