use crate::error::InputError;

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum Operation {
    GetGlobal = 1,
    CallGlobal = 2,
    And = 3,
    Or = 4,
    Not = 5,
    Plus = 6,
    Minus = 7,
    Multiply = 8,
    Divide = 9,
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

impl From<Operation> for u32 {
    fn from(op: Operation) -> Self {
        op as u32
    }
}

impl TryFrom<u32> for Operation {
    type Error = InputError;

    fn try_from(value: u32) -> Result<Self, Self::Error> {
        if value <= Self::CloseUpvalue as u32 {
            // TODO - this is unhinged
            Ok(unsafe { std::mem::transmute(value as u8) })
        } else {
            Err(InputError::InvalidOperation(value))
        }
    }
}

#[cfg(test)]
mod test {
    use serde_json::Value;

    use super::Operation;

    #[test]
    pub fn parse_bytecode() {
        let examples = include_str!("../tests/static/bytecode_examples.jsonl");
        for example in examples.lines() {
            let _res: Vec<Value> = serde_json::from_str(example).unwrap();
        }
    }
}
