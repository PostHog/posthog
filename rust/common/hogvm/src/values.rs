use std::{collections::HashMap, str::FromStr};

use crate::{
    error::VmError,
    memory::{HeapReference, VmHeap},
};

#[derive(Debug, Clone, PartialEq)]
pub enum Num {
    Integer(i64),
    Float(f64),
}

#[derive(Debug, Clone, PartialEq)]
pub enum CallableType {
    Local,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Callable {
    Local(LocalCallable),
}

#[derive(Debug, Clone, PartialEq)]
pub struct Closure {
    pub captures: Vec<HeapReference>,
    pub callable: Callable,
}

#[derive(Debug, Clone, PartialEq)]
pub struct LocalCallable {
    pub name: String,
    pub stack_arg_count: usize,
    pub capture_count: usize,
    pub ip: usize,
}

impl From<LocalCallable> for Callable {
    fn from(local_callable: LocalCallable) -> Self {
        Callable::Local(local_callable)
    }
}

// hog has "primitives", which are copied by e.g, "get_local", and "objects", which are passed around by reference. This is distinct from the
// "Heap" allocated stuff, which is used for things which must outlive all references to themselves on the stack, e.g. upvalues.

#[derive(Debug, Clone, PartialEq)]
pub enum HogLiteral {
    Number(Num),
    Boolean(bool),
    String(String),
    Array(Vec<HogValue>),
    Object(HashMap<String, HogValue>),
    Callable(Callable),
    Closure(Closure),
    Null,
}

#[derive(Debug, Clone, PartialEq)]
pub enum HogValue {
    Lit(HogLiteral),
    Ref(HeapReference),
}

// Basically, for anything we want to be able to cheaply convert try and convert a hog value into, e.g.
// a bool or an int, but also for ref types, like a &str or a &[HogValue]
pub trait FromHogRef {
    fn from_ref(value: &HogLiteral) -> Result<&Self, VmError>;
}

// For anything where we want to deconstruct the hog value, like a String or an Array
pub trait FromHogLiteral: Sized {
    fn from_val(value: HogLiteral) -> Result<Self, VmError>;
}

impl HogValue {
    pub fn type_name(&self) -> &str {
        let Self::Lit(literal) = self else {
            return "Reference";
        };
        literal.type_name()
    }

    pub fn deref<'a, 'b: 'a>(&'a self, heap: &'b VmHeap) -> Result<&HogLiteral, VmError> {
        match self {
            HogValue::Lit(lit) => Ok(lit),
            HogValue::Ref(ptr) => heap.deref(*ptr),
        }
    }

    pub fn get_nested<'a, 'b: 'a>(
        &'a self,
        chain: &[HogValue],
        heap: &'b VmHeap,
    ) -> Result<Option<&'a HogValue>, VmError> {
        if chain.len() == 0 {
            return Ok(Some(self));
        }

        let lit = match self {
            HogValue::Lit(lit) => lit,
            HogValue::Ref(ptr) => heap.deref(*ptr)?,
        };

        match lit {
            HogLiteral::Object(map) => {
                let key: &str = chain[0].deref(heap)?.try_as()?;
                let Some(found) = map.get(key) else {
                    return Ok(None);
                };
                found.get_nested(&chain[1..], heap)
            }
            HogLiteral::Array(vals) => {
                let index: &Num = chain[0].deref(heap)?.try_as()?;
                if index.is_float() || index.to_integer() < 1 {
                    return Err(VmError::InvalidIndex);
                }
                let index = (index.to_integer() as usize) - 1; // Hog indices are 1 based
                let Some(found) = vals.get(index) else {
                    return Ok(None);
                };
                found.get_nested(&chain[1..], heap)
            }
            _ => Ok(None),
        }
    }

    pub fn equals(&self, rhs: &HogValue, heap: &VmHeap) -> Result<HogLiteral, VmError> {
        let (lhs, rhs) = (self.deref(heap)?, rhs.deref(heap)?);
        lhs.equals(rhs)
    }

    pub fn not_equals(&self, rhs: &HogValue, heap: &VmHeap) -> Result<HogLiteral, VmError> {
        self.equals(rhs, heap)?.not()
    }

    pub fn contains(&self, other: &HogValue, heap: &VmHeap) -> Result<HogLiteral, VmError> {
        let (haystack, needle) = (self.deref(heap)?, other.deref(heap)?);
        match haystack {
            HogLiteral::String(s) => {
                let needle: &str = needle.try_as()?;
                Ok(s.contains(needle).into())
            }
            HogLiteral::Array(vals) => {
                for val in vals.iter() {
                    if *val.equals(other, heap)?.try_as::<bool>()? {
                        return Ok(true.into());
                    }
                }
                Ok(false.into())
            }
            HogLiteral::Object(map) => {
                let key: &str = needle.try_as()?;
                Ok(map.contains_key(key).into())
            }
            _ => Err(VmError::CannotCoerce(
                self.type_name().to_string(),
                other.type_name().to_string(),
            )),
        }
    }
}

impl HogLiteral {
    pub fn type_name(&self) -> &str {
        match self {
            HogLiteral::String(_) => "String",
            HogLiteral::Number(_) => "Number",
            HogLiteral::Boolean(_) => "Boolean",
            HogLiteral::Array(_) => "Array",
            HogLiteral::Object(_) => "Object",
            HogLiteral::Null => "Null",
            HogLiteral::Callable(_) => "Callable",
            HogLiteral::Closure(_) => "Closure",
        }
    }

    pub fn try_as<T: ?Sized>(&self) -> Result<&T, VmError>
    where
        T: FromHogRef,
    {
        T::from_ref(self)
    }

    pub fn try_into<T: ?Sized>(self) -> Result<T, VmError>
    where
        T: FromHogLiteral,
    {
        T::from_val(self)
    }

    pub fn and(&self, rhs: &HogLiteral) -> Result<HogLiteral, VmError> {
        Ok(Self::Boolean(*self.try_as()? && *rhs.try_as()?))
    }

    pub fn or(&self, rhs: &HogLiteral) -> Result<HogLiteral, VmError> {
        Ok(Self::Boolean(*self.try_as()? || *rhs.try_as()?))
    }

    pub fn not(&self) -> Result<HogLiteral, VmError> {
        Ok(Self::Boolean(!*self.try_as::<bool>()?))
    }

    fn coerce_types(&self, rhs: &HogLiteral) -> Result<(HogLiteral, HogLiteral), VmError> {
        // TODO - it's a bit sad that coercing allocates. It's /correct/ (coercing is only used for equality checks, the cloned values are immediately dropped,
        // but it's still a bit sad)
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

        use HogLiteral::*;

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

    fn equals(&self, rhs: &HogLiteral) -> Result<HogLiteral, VmError> {
        let (lhs, rhs) = self.coerce_types(rhs)?;
        Ok((lhs == rhs).into())
    }

    pub fn set_property(&mut self, key: HogLiteral, val: HogValue) -> Result<(), VmError> {
        match self {
            HogLiteral::Array(vals) => {
                let index: Num = key.try_into()?;
                if index.is_float() || index.to_integer() < 1 {
                    return Err(VmError::InvalidIndex);
                }
                let index = index.to_integer() as usize - 1;
                if index >= vals.len() {
                    return Err(VmError::IndexOutOfBounds(index, vals.len()));
                }
                vals[index] = val;
            }
            HogLiteral::Object(map) => {
                let key: String = key.try_into()?;
                map.insert(key, val);
            }
            _ => return Err(VmError::ExpectedObject),
        };

        Ok(())
    }
}

impl FromHogLiteral for HogLiteral {
    fn from_val(value: HogLiteral) -> Result<Self, VmError> {
        Ok(value)
    }
}

impl FromHogLiteral for String {
    fn from_val(value: HogLiteral) -> Result<Self, VmError> {
        let HogLiteral::String(s) = value else {
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
    fn from_ref(value: &HogLiteral) -> Result<&Self, VmError> {
        match value {
            HogLiteral::Boolean(b) => Ok(b),
            HogLiteral::Null => Ok(&false), // Coerce nulls to false
            _ => Err(VmError::InvalidValue(
                value.type_name().to_string(),
                "Boolean".to_string(),
            )),
        }
    }
}

impl FromHogRef for Num {
    fn from_ref(value: &HogLiteral) -> Result<&Self, VmError> {
        match value {
            HogLiteral::Number(n) => Ok(n),
            _ => Err(VmError::InvalidValue(
                value.type_name().to_string(),
                "Number".to_string(),
            )),
        }
    }
}

impl FromHogRef for str {
    fn from_ref(value: &HogLiteral) -> Result<&Self, VmError> {
        match value {
            HogLiteral::String(s) => Ok(s),
            _ => Err(VmError::InvalidValue(
                value.type_name().to_string(),
                "String".to_string(),
            )),
        }
    }
}

impl FromHogRef for Callable {
    fn from_ref(value: &HogLiteral) -> Result<&Self, VmError> {
        match value {
            HogLiteral::Callable(c) => Ok(c),
            _ => Err(VmError::InvalidValue(
                value.type_name().to_string(),
                "Callable".to_string(),
            )),
        }
    }
}

impl<T> From<T> for HogValue
where
    T: Into<HogLiteral>,
{
    fn from(value: T) -> Self {
        HogValue::Lit(value.into())
    }
}

impl<T> FromHogLiteral for T
where
    T: FromHogRef + Clone,
{
    fn from_val(value: HogLiteral) -> Result<Self, VmError> {
        value.try_as::<T>().cloned()
    }
}

impl From<bool> for HogLiteral {
    fn from(value: bool) -> Self {
        Self::Boolean(value)
    }
}

impl From<String> for HogLiteral {
    fn from(value: String) -> Self {
        Self::String(value)
    }
}

impl From<i64> for HogLiteral {
    fn from(value: i64) -> Self {
        Self::Number(Num::Integer(value))
    }
}

impl From<f64> for HogLiteral {
    fn from(value: f64) -> Self {
        Self::Number(Num::Float(value))
    }
}

impl From<Vec<HogValue>> for HogLiteral {
    fn from(value: Vec<HogValue>) -> Self {
        Self::Array(value)
    }
}

impl From<HashMap<String, HogValue>> for HogLiteral {
    fn from(value: HashMap<String, HogValue>) -> Self {
        Self::Object(value)
    }
}

impl From<Num> for HogLiteral {
    fn from(num: Num) -> Self {
        HogLiteral::Number(num)
    }
}

impl From<HeapReference> for HogValue {
    fn from(value: HeapReference) -> Self {
        HogValue::Ref(value)
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

    pub fn binary_op(op: NumOp, a: &Num, b: &Num) -> Result<HogLiteral, VmError> {
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
