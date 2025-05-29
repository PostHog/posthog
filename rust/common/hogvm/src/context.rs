use serde_json::{json, Value as JsonValue};
use std::collections::HashMap;

use crate::{
    error::VmError,
    stl::{stl_map, NativeFunction},
    vm::HogVM,
};

/// The read-only context for the virtual machine. Defines
pub struct ExecutionContext<'a> {
    pub bytecode: &'a [JsonValue],
    // TODO - this could and should be borrowed, it's read-only anyway
    pub globals: JsonValue, // Generally an object, but can be anything really

    pub max_stack_depth: usize,
    pub max_heap_size: usize,
    pub max_steps: usize,
    pub native_fns: HashMap<String, NativeFunction>,
}

impl<'a> ExecutionContext<'a> {
    pub fn new(
        bytecode: &'a [JsonValue],
        globals: JsonValue,
        max_stack_depth: usize,
        max_heap_size: usize,
        max_steps: usize,
        native_fns: HashMap<String, NativeFunction>,
    ) -> Self {
        Self {
            bytecode,
            globals,
            max_stack_depth,
            max_heap_size,
            max_steps,
            native_fns,
        }
    }

    pub fn with_defaults(bytecode: &'a [JsonValue]) -> Self {
        let fns = stl_map();
        // TODO - these are basically randomly chosen
        Self::new(bytecode, json!({}), 128, 1024 * 1024, 10_000, fns)
    }

    pub fn with_ext_fn(mut self, name: String, func: NativeFunction) -> Self {
        self.native_fns.insert(name, func);
        self
    }

    pub fn with_ext_fns(mut self, fns: HashMap<String, NativeFunction>) -> Self {
        self.native_fns.extend(fns);
        self
    }

    pub fn set_fns(mut self, fns: HashMap<String, NativeFunction>) -> Self {
        self.native_fns = fns;
        self
    }

    pub fn with_globals(mut self, globals: JsonValue) -> Self {
        self.globals = globals;
        self
    }

    pub fn with_max_stack_depth(mut self, max_stack_depth: usize) -> Self {
        self.max_stack_depth = max_stack_depth;
        self
    }

    pub fn with_max_heap_size(mut self, max_heap_size: usize) -> Self {
        self.max_heap_size = max_heap_size;
        self
    }

    pub fn with_max_steps(mut self, max_steps: usize) -> Self {
        self.max_steps = max_steps;
        self
    }

    pub fn to_vm(&self) -> Result<HogVM, VmError> {
        HogVM::new(self)
    }
}
