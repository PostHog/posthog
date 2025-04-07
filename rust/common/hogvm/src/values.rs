use std::{collections::HashMap, str::FromStr};

use crate::error::VmError;

#[derive(Debug, Clone, PartialEq)]
pub enum Num {
    Integer(i64),
    Float(f64),
}

#[derive(Debug, Clone, PartialEq)]
pub enum CallableType {
    Local,
}

// TODO - this could probably be an enum based on the CallableType
#[derive(Debug, Clone, PartialEq)]
pub enum Callable {
    Local {
        name: String,
        stack_arg_count: usize,
        heap_arg_count: usize,
        ip: usize,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub enum HogValue {
    Number(Num),
    Boolean(bool),
    String(String),
    Array(Vec<HogValue>),
    Object(HashMap<String, HogValue>),
    Callable(Callable),
    Null,
}

// Basically, for anything we want to be able to cheaply convert try and convert a hog value into, e.g.
// a bool or an int, but also for ref types, like a &str or a &[HogValue]
pub trait FromHogRef {
    fn from_ref(value: &HogValue) -> Result<&Self, VmError>;
}

// For anything where we want to deconstruct the hog value, like a String or an Array
pub trait FromHogValue: Sized {
    fn from_val(value: HogValue) -> Result<Self, VmError>;
}

impl HogValue {
    pub fn type_name(&self) -> &str {
        match self {
            Self::String(_) => "String",
            Self::Number(_) => "Number",
            Self::Boolean(_) => "Boolean",
            Self::Array(_) => "Array",
            Self::Object(_) => "Object",
            Self::Null => "Null",
            Self::Callable(_) => "Callable",
        }
    }

    pub fn try_as<T: ?Sized>(&self) -> Result<&T, VmError>
    where
        T: FromHogRef,
    {
        T::from_ref(self)
    }

    pub fn try_into<T>(self) -> Result<T, VmError>
    where
        T: FromHogValue,
    {
        T::from_val(self)
    }

    pub fn get_nested<S: AsRef<str>>(&self, chain: &[S]) -> Option<&HogValue> {
        if chain.len() == 0 {
            return Some(self);
        }

        match self {
            Self::Object(map) => {
                let key = chain.first().unwrap();
                map.get(key.as_ref())
                    .and_then(|value| value.get_nested(&chain[1..]))
            }
            _ => None,
        }
    }

    pub fn get_nested_mut<S: AsRef<str>>(&mut self, chain: &[S]) -> Option<&mut HogValue> {
        if chain.len() == 0 {
            return Some(self);
        }

        match self {
            Self::Object(map) => {
                let key = chain.first().unwrap();
                map.get_mut(key.as_ref())
                    .and_then(|value| value.get_nested_mut(&chain[1..]))
            }
            _ => None,
        }
    }

    pub fn and(&self, rhs: &HogValue) -> Result<HogValue, VmError> {
        Ok(Self::Boolean(*self.try_as()? && *rhs.try_as()?))
    }

    pub fn or(&self, rhs: &HogValue) -> Result<HogValue, VmError> {
        Ok(Self::Boolean(*self.try_as()? || *rhs.try_as()?))
    }

    pub fn not(&self) -> Result<HogValue, VmError> {
        Ok(Self::Boolean(!*self.try_as::<bool>()?))
    }

    fn coerce_types(&self, rhs: &HogValue) -> Result<(HogValue, HogValue), VmError> {
        // TODO - it's a bit sad that coercing allocates
        let fail = || {
            Err(VmError::CannotCoerce(
                self.type_name().to_string(),
                rhs.type_name().to_string(),
            ))
        };

        let mfail = |_| fail().unwrap_err();

        // It's particularly sad that it allocates on the hot path
        if self.type_name() == rhs.type_name() {
            return Ok((self.clone(), rhs.clone()));
        }

        use HogValue::*;

        match (self.clone(), rhs.clone()) {
            (Number(a), Boolean(b)) => Ok((a.into(), (if b { 1 } else { 0 }).into())),
            (Boolean(a), Number(b)) => Ok(((if a { 1 } else { 0 }).into(), b.into())),

            (Number(a), String(b)) => {
                let b = Num::from_str(&b).map_err(mfail)?;
                Ok((a.into(), b.into()))
            }
            (String(a), Number(b)) => {
                let a = Num::from_str(&a).map_err(mfail)?;
                Ok((a.into(), b.into()))
            }

            (String(a), Boolean(b)) => Ok(((a.to_lowercase() == "true").into(), b.into())),
            (Boolean(a), String(b)) => Ok((a.into(), (b.to_lowercase() == "true").into())),

            _ => fail(),
        }
    }

    pub fn equals(&self, rhs: &HogValue) -> Result<HogValue, VmError> {
        let (lhs, rhs) = self.coerce_types(rhs)?;
        Ok((lhs == rhs).into())
    }

    pub fn not_equals(&self, other: &HogValue) -> Result<HogValue, VmError> {
        self.equals(other)?.not()
    }

    pub fn contains(&self, other: &HogValue) -> Result<HogValue, VmError> {
        match self {
            HogValue::String(s) => {
                let needle: &str = other.try_as()?;
                Ok(s.contains(needle).into())
            }
            HogValue::Array(vals) => Ok(vals.contains(other).into()),
            HogValue::Object(map) => {
                let key: &str = other.try_as()?;
                Ok(map.contains_key(key).into())
            }
            _ => Err(VmError::CannotCoerce(
                self.type_name().to_string(),
                other.type_name().to_string(),
            )),
        }
    }
}

impl FromHogValue for String {
    fn from_val(value: HogValue) -> Result<Self, VmError> {
        let HogValue::String(s) = value else {
            return Err(VmError::InvalidValue(
                value.type_name().to_string(),
                "String".to_string(),
            ));
        };
        Ok(s)
    }
}

// TODO - hog values are actually "truthy", as in, will coerce to boolean
// true for all non-null values
impl FromHogRef for bool {
    fn from_ref(value: &HogValue) -> Result<&Self, VmError> {
        match value {
            HogValue::Boolean(b) => Ok(b),
            HogValue::Null => Ok(&false), // Coerce nulls to false
            _ => Err(VmError::InvalidValue(
                value.type_name().to_string(),
                "Boolean".to_string(),
            )),
        }
    }
}

impl FromHogRef for Num {
    fn from_ref(value: &HogValue) -> Result<&Self, VmError> {
        match value {
            HogValue::Number(n) => Ok(n),
            _ => Err(VmError::InvalidValue(
                value.type_name().to_string(),
                "Number".to_string(),
            )),
        }
    }
}

impl FromHogRef for str {
    fn from_ref(value: &HogValue) -> Result<&Self, VmError> {
        match value {
            HogValue::String(s) => Ok(s),
            _ => Err(VmError::InvalidValue(
                value.type_name().to_string(),
                "String".to_string(),
            )),
        }
    }
}

impl FromHogRef for Callable {
    fn from_ref(value: &HogValue) -> Result<&Self, VmError> {
        match value {
            HogValue::Callable(c) => Ok(c),
            _ => Err(VmError::InvalidValue(
                value.type_name().to_string(),
                "Callable".to_string(),
            )),
        }
    }
}

impl<T> FromHogValue for T
where
    T: FromHogRef + Clone,
{
    fn from_val(value: HogValue) -> Result<Self, VmError> {
        value.try_as::<T>().cloned()
    }
}

impl From<bool> for HogValue {
    fn from(value: bool) -> Self {
        Self::Boolean(value)
    }
}

impl From<String> for HogValue {
    fn from(value: String) -> Self {
        Self::String(value)
    }
}

impl From<i64> for HogValue {
    fn from(value: i64) -> Self {
        Self::Number(Num::Integer(value))
    }
}

impl From<f64> for HogValue {
    fn from(value: f64) -> Self {
        Self::Number(Num::Float(value))
    }
}

impl From<Vec<HogValue>> for HogValue {
    fn from(value: Vec<HogValue>) -> Self {
        Self::Array(value)
    }
}

impl From<HashMap<String, HogValue>> for HogValue {
    fn from(value: HashMap<String, HogValue>) -> Self {
        Self::Object(value)
    }
}

impl From<Num> for HogValue {
    fn from(num: Num) -> Self {
        HogValue::Number(num)
    }
}

#[derive(Debug, Clone, Copy)]
pub enum NumOp {
    Add,
    Sub,
    Mul,
    Div,
    Mod,
    Gt,
    Lt,
    Gte,
    Lte,
}

impl From<i64> for Num {
    fn from(value: i64) -> Self {
        Num::Integer(value)
    }
}

impl From<f64> for Num {
    fn from(value: f64) -> Self {
        Num::Float(value)
    }
}

impl FromStr for Num {
    type Err = VmError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        if let Ok(value) = s.parse::<i64>() {
            Ok(Num::Integer(value))
        } else if let Ok(value) = s.parse::<f64>() {
            Ok(Num::Float(value))
        } else {
            Err(VmError::InvalidNumber(s.to_string()))
        }
    }
}

impl Num {
    pub fn is_float(&self) -> bool {
        matches!(self, Num::Float(_))
    }

    pub fn is_integer(&self) -> bool {
        matches!(self, Num::Integer(_))
    }

    pub fn to_float(&self) -> f64 {
        match self {
            Num::Float(value) => *value,
            Num::Integer(value) => *value as f64,
        }
    }

    pub fn to_integer(&self) -> i64 {
        match self {
            Num::Float(value) => *value as i64,
            Num::Integer(value) => *value,
        }
    }

    pub fn binary_op(op: NumOp, a: &Num, b: &Num) -> Result<HogValue, VmError> {
        let needs_coerce = a.is_float() || b.is_float();
        if needs_coerce {
            let a = a.to_float();
            let b = b.to_float();
            match op {
                NumOp::Add => Ok((a + b).into()),
                NumOp::Sub => Ok((a - b).into()),
                NumOp::Mul => Ok((a * b).into()),
                NumOp::Div => Ok((a / b).into()),
                NumOp::Mod => Ok((a % b).into()),
                NumOp::Gt => Ok((a > b).into()),
                NumOp::Lt => Ok((a < b).into()),
                NumOp::Gte => Ok((a >= b).into()),
                NumOp::Lte => Ok((a <= b).into()),
            }
        } else {
            let a = a.to_integer();
            let b = b.to_integer();

            if b == 0 && matches!(op, NumOp::Div | NumOp::Mod) {
                return Err(VmError::DivisionByZero);
            }

            match op {
                NumOp::Add => Ok((a + b).into()),
                NumOp::Sub => Ok((a - b).into()),
                NumOp::Mul => Ok((a * b).into()),
                NumOp::Div => Ok((a / b).into()),
                NumOp::Mod => Ok((a % b).into()),
                NumOp::Gt => Ok((a > b).into()),
                NumOp::Lt => Ok((a < b).into()),
                NumOp::Gte => Ok((a >= b).into()),
                NumOp::Lte => Ok((a <= b).into()),
            }
        }
    }
}
