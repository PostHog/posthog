use std::collections::HashMap;
use std::sync::Arc;

use serde_json::{Number, Value as JsonValue};

use crate::VmError;

/// A bytecode token pre-decoded out of its `JsonValue` representation, so the interpreter's
/// per-step fetches are enum matches instead of serde deserializations. Decoded once per
/// program/module body, index-aligned with the raw token array (jump offsets and `ip` semantics
/// are unchanged).
#[derive(Debug, Clone)]
pub enum Token {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(Arc<str>),
    /// Anything else (arrays/objects, numbers representable neither as i64 nor f64). Rare —
    /// consumers fall back to their `JsonValue` handling.
    Json(JsonValue),
}

impl Token {
    fn from_json(value: &JsonValue) -> Token {
        match value {
            JsonValue::Null => Token::Null,
            JsonValue::Bool(b) => Token::Bool(*b),
            JsonValue::Number(n) => {
                if let Some(i) = n.as_i64() {
                    Token::Int(i)
                } else if let Some(f) = n.as_f64() {
                    Token::Float(f)
                } else {
                    Token::Json(value.clone())
                }
            }
            JsonValue::String(s) => Token::Str(Arc::from(s.as_str())),
            other => Token::Json(other.clone()),
        }
    }

    pub fn type_name(&self) -> &'static str {
        match self {
            Token::Null => "null",
            Token::Bool(_) => "bool",
            Token::Int(_) | Token::Float(_) => "number",
            Token::Str(_) => "string",
            Token::Json(JsonValue::Array(_)) => "array",
            Token::Json(JsonValue::Object(_)) => "object",
            Token::Json(_) => "json",
        }
    }
}

pub(crate) fn decode_tokens(tokens: &[JsonValue]) -> Vec<Token> {
    tokens.iter().map(Token::from_json).collect()
}

// A top-level hog program - functionally the body of a "main" function, if hog had such a thing.
// `bytecode` is `Arc`-shared so building a program from shared bytecode is a refcount bump, and
// the decoded token stream is shared the same way — cloning a `Program` never re-decodes.
#[derive(Clone)]
pub struct Program {
    bytecode: Arc<Vec<JsonValue>>,
    decoded: Arc<Vec<Token>>,
    version: u64,
    program_start_offset: usize,
}

// A referenceable module, exporting a set of functions. Top level programs can jump into module code
#[derive(Debug, Clone, Default)]
pub struct Module {
    functions: HashMap<String, ExportedFunction>,
}

#[derive(Debug, Clone)]
pub struct ExportedFunction {
    arg_count: usize,
    body: Vec<JsonValue>,
    decoded: Vec<Token>,
}

impl Program {
    pub fn new(bytecode: Vec<JsonValue>) -> Result<Self, VmError> {
        Self::from_shared(Arc::new(bytecode))
    }

    /// Build a program from `Arc`-shared bytecode without copying it — for bytecode held in a shared
    /// catalog and evaluated repeatedly.
    pub fn from_shared(bytecode: Arc<Vec<JsonValue>>) -> Result<Self, VmError> {
        if bytecode.is_empty() {
            return Err(VmError::InvalidBytecode(
                "Missing bytecode marker at position 0".to_string(),
            ));
        }

        let mut to_skip = 1; // Skip the bytecode marker

        let bytecode_marker = bytecode[0].clone();

        let version = match bytecode_marker {
            JsonValue::String(s) if s == "_H" => {
                let version = bytecode.get(1).cloned();
                if version.is_some() {
                    to_skip += 1; // Skip the version marker
                }
                let version = version.unwrap_or(JsonValue::Number(Number::from(0)));
                match version {
                    JsonValue::Number(n) => n.as_u64().ok_or_else(|| {
                        VmError::InvalidBytecode("Invalid version number".to_string())
                    })?,
                    _ => {
                        return Err(VmError::InvalidBytecode(
                            "Invalid version number".to_string(),
                        ))
                    }
                }
            }
            _ => {
                return Err(VmError::InvalidBytecode(format!(
                    "Invalid bytecode marker: {bytecode_marker:?}"
                )))
            }
        };

        let program = Program {
            decoded: Arc::new(decode_tokens(&bytecode)),
            bytecode,
            version,
            program_start_offset: to_skip,
        };

        Ok(program)
    }

    pub fn get(&self, idx: usize) -> Option<&JsonValue> {
        self.bytecode.get(idx + self.program_start_offset)
    }

    pub fn get_token(&self, idx: usize) -> Option<&Token> {
        self.decoded.get(idx + self.program_start_offset)
    }

    /// The decoded body (header stripped), so `body_tokens()[ip]` == `get_token(ip)`. The VM
    /// caches this slice per chunk to keep the per-step fetch a plain bounds-checked index.
    pub fn body_tokens(&self) -> &[Token] {
        &self.decoded[self.program_start_offset..]
    }

    pub fn version(&self) -> u64 {
        self.version
    }

    /// The full bytecode array, header included — used to populate the reference VM's
    /// `bytecodes.root.bytecode` in a snapshot.
    pub fn tokens(&self) -> &[JsonValue] {
        &self.bytecode
    }

    /// Number of header tokens (`_H` + version) before the first opcode. The reference VM's
    /// per-frame `ip` is an index into the full array (header included), whereas our `ip` is
    /// body-relative, so root-chunk ips differ by exactly this offset.
    pub fn header_len(&self) -> usize {
        self.program_start_offset
    }
}

impl Module {
    pub fn new() -> Self {
        Module {
            functions: HashMap::new(),
        }
    }

    pub fn add_function(&mut self, name: String, function: ExportedFunction) {
        self.functions.insert(name, function);
    }

    pub fn functions(&self) -> &HashMap<String, ExportedFunction> {
        &self.functions
    }
}

impl ExportedFunction {
    pub fn new(arg_count: usize, bytecode: Vec<JsonValue>) -> Self {
        ExportedFunction {
            arg_count,
            decoded: decode_tokens(&bytecode),
            body: bytecode,
        }
    }

    pub fn arg_count(&self) -> usize {
        self.arg_count
    }

    pub fn get(&self, idx: usize) -> Option<&JsonValue> {
        self.body.get(idx)
    }

    pub fn get_token(&self, idx: usize) -> Option<&Token> {
        self.decoded.get(idx)
    }

    /// The decoded body as a slice (see [`Program::body_tokens`]).
    pub fn body_tokens(&self) -> &[Token] {
        &self.decoded
    }
}
