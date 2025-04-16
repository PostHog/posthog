use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::error::VmError;

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(try_from = "Value")]
pub enum Operation {
    GetGlobal = 1,
    CallGlobal = 2,
    And = 3,
    Or = 4,
    Not = 5,
    Plus = 6,
    Minus = 7,
    Mult = 8,
    Div = 9,
    Mod = 10,
    Eq = 11,
    NotEq = 12,
    Gt = 13,
    GtEq = 14,
    Lt = 15,
    LtEq = 16,
    Like = 17,
    Ilike = 18,
    NotLike = 19,
    NotIlike = 20,
    In = 21,
    NotIn = 22,
    Regex = 23,
    NotRegex = 24,
    Iregex = 25,
    NotIregex = 26,
    InCohort = 27,
    NotInCohort = 28,
    True = 29,
    False = 30,
    Null = 31,
    String = 32,
    Integer = 33,
    Float = 34,
    Pop = 35,
    GetLocal = 36,
    SetLocal = 37,
    Return = 38,
    Jump = 39,
    JumpIfFalse = 40,
    DeclareFn = 41,
    Dict = 42,
    Array = 43,
    Tuple = 44,
    GetProperty = 45,
    SetProperty = 46,
    JumpIfStackNotNull = 47,
    GetPropertyNullish = 48,
    Throw = 49,
    Try = 50,
    PopTry = 51,
    Callable = 52,
    Closure = 53,
    CallLocal = 54,
    GetUpvalue = 55,
    SetUpvalue = 56,
    CloseUpvalue = 57,
}

impl From<Operation> for Value {
    fn from(op: Operation) -> Self {
        Value::Number((op as u8).into())
    }
}

impl TryFrom<Value> for Operation {
    type Error = VmError;

    fn try_from(val: Value) -> Result<Self, Self::Error> {
        let Some(num) = val.as_i64() else {
            return Err(VmError::NotAnOperation(val));
        };

        if num >= Self::GetGlobal as i64 && num <= Self::CloseUpvalue as i64 {
            // TODO - this is deeply unhinged
            Ok(unsafe { std::mem::transmute::<u8, Operation>(num as u8) })
        } else {
            Err(VmError::InvalidOperation(val))
        }
    }
}

#[cfg(test)]
mod test {
    use serde_json::Value;

    #[test]
    pub fn parse_bytecode() {
        let examples = include_str!("../tests/static/bytecode_examples.jsonl");
        for example in examples.lines() {
            let _res: Vec<Value> = serde_json::from_str(example).unwrap();
        }
    }
}
