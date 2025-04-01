use std::{any::Any, collections::HashMap};

use serde::de::DeserializeOwned;
use serde_json::Value as JsonValue;

use crate::{
    error::{Error, VmError},
    ops::Operation,
    util::like,
    values::{FromHogValue, HogValue},
};

pub struct ExecutionContext<'a> {
    bytecode: &'a [JsonValue],
    globals: HashMap<String, HogValue>,
    max_stack_depth: usize,
}

pub struct VmState<'a> {
    stack: Vec<HogValue>,
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

    fn try_import(&self, chain: &[String]) -> Result<HogValue, VmError> {
        todo!()
    }

    pub fn step(&mut self) -> Result<Option<()>, VmError> {
        let op: Operation = self.next()?;

        match op {
            Operation::GetGlobal => {
                // GetGlobal is used to do 1 of 2 things, either push a value from a global variable onto the stack, or push a new hog
                // closure onto the stack, potentially from an STL function (as far as I can tell, this is how imports work)
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
                } else if let Ok(closure) = self.try_import(&chain) {
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
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.plus(&b)?)?;
            }
            Operation::Minus => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.minus(&b)?)?;
            }
            Operation::Mult => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.multiply(&b)?)?;
            }
            Operation::Div => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.divide(&b)?)?;
            }
            Operation::Mod => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.modulo(&b)?)?;
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
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.gt(&b)?)?;
            }
            Operation::GtEq => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.gte(&b)?)?;
            }
            Operation::Lt => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.lt(&b)?)?;
            }
            Operation::LtEq => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.lte(&b)?)?;
            }
            Operation::Like => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(like(a.try_as::<String>()?, b.try_as::<String>()?, true))?;
            }
            Operation::Ilike => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(like(a.try_as::<String>()?, b.try_as::<String>()?, false))?;
            }
            Operation::NotLike => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(!like(a.try_as::<String>()?, b.try_as::<String>()?, true))?;
            }
            Operation::NotIlike => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(!like(a.try_as::<String>()?, b.try_as::<String>()?, false))?;
            }
            Operation::In => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.contains(&b)?)?;
            }
            Operation::NotIn => {
                let (a, b) = (self.pop_stack()?, self.pop_stack()?);
                self.push_stack(a.contains(&b)?.not()?)?;
            }
            Operation::Regex => return Err(VmError::NotImplemented("Regex".to_string())),
            Operation::NotRegex => return Err(VmError::NotImplemented("NotRegex".to_string())),
            Operation::Iregex => return Err(VmError::NotImplemented("Iregex".to_string())),
            Operation::NotIregex => return Err(VmError::NotImplemented("NotIregex".to_string())),
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
