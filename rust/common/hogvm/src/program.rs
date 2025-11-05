use std::collections::HashMap;

use serde_json::{Number, Value as JsonValue};

use crate::VmError;

// A top-level hog program - functionally the body of a "main" function, if hog had such a thing
pub struct Program {
    bytecode: Vec<JsonValue>,
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
}

impl Program {
    pub fn new(bytecode: Vec<JsonValue>) -> Result<Self, VmError> {
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
                    "Invalid bytecode marker: {bytecode_marker:?}"
                )))
            }
        };

        let program = Program {
            bytecode,
            version,
            program_start_offset: to_skip,
        };

        Ok(program)
    }

    pub fn get(&self, idx: usize) -> Option<&JsonValue> {
        self.bytecode.get(idx + self.program_start_offset)
    }

    pub fn version(&self) -> u64 {
        self.version
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
            body: bytecode,
        }
    }

    pub fn arg_count(&self) -> usize {
        self.arg_count
    }

    pub fn get(&self, idx: usize) -> Option<&JsonValue> {
        self.body.get(idx)
    }
}
