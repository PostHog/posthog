use serde_json::{json, Value as JsonValue};
use std::collections::HashMap;

use crate::{
    error::VmError,
    program::{ExportedFunction, Module, Program},
    stl::{hog_stl_map, stl_map, NativeFunction},
    vm::HogVM,
    HogLiteral, HogValue,
};

/// The read-only context for the virtual machine.
pub struct ExecutionContext {
    program: Program,
    // TODO - this could and should be borrowed, it's read-only anyway and often the most expensive bit of the context
    pub globals: JsonValue, // Generally an object, but can be anything really

    pub max_stack_depth: usize,
    pub max_heap_size: usize,
    pub max_steps: usize,
    native_fns: HashMap<String, NativeFunction>,
    symbol_table: HashMap<Symbol, ExportedFunction>, // Flattened symbol table of all imported hog modules
}

#[derive(Debug, Clone, Hash, Eq, PartialEq)]
pub struct Symbol {
    pub name: String,
    pub module: String,
}

impl ExecutionContext {
    pub fn new(
        program: Program,
        globals: JsonValue,
        max_stack_depth: usize,
        max_heap_size: usize,
        max_steps: usize,
        native_fns: HashMap<String, NativeFunction>,
        modules: HashMap<String, Module>,
    ) -> Self {
        Self {
            program,
            globals,
            max_stack_depth,
            max_heap_size,
            max_steps,
            native_fns,
            symbol_table: HashMap::new(),
        }
        .with_modules(&modules)
    }

    pub fn with_defaults(bytecode: Program) -> Self {
        // TODO - these values are basically randomly chosen
        Self::new(
            bytecode,
            json!({}),
            128,
            1024 * 1024,
            10_000,
            stl_map(),
            hog_stl_map(),
        )
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

    pub fn with_modules(mut self, modules: &HashMap<String, Module>) -> Self {
        self.symbol_table.clear();
        for (name, module) in modules.iter() {
            self = self.add_module(name.clone(), module);
        }
        self
    }

    pub fn add_module(mut self, name: String, module: &Module) -> Self {
        for (fn_name, function) in module.functions().iter() {
            self.symbol_table
                .insert(Symbol::new(&name, fn_name), function.clone());
        }
        self
    }

    pub fn to_vm(&self) -> Result<HogVM, VmError> {
        HogVM::new(self)
    }

    pub fn has_symbol(&self, symbol: &Symbol) -> bool {
        self.symbol_table.contains_key(symbol)
    }

    pub fn get_symbol(&self, symbol: &Symbol) -> Result<&ExportedFunction, VmError> {
        self.symbol_table
            .get(symbol)
            .ok_or(VmError::UnknownSymbol(symbol.to_string()))
    }

    pub fn execute_native_function_call(
        &self,
        vm: &mut HogVM,
        name: &str,
        args: Vec<HogValue>,
    ) -> Result<(), VmError> {
        let Some(native_fn) = self.native_fns.get(name) else {
            return Err(VmError::UnknownFunction(name.to_string()));
        };
        let result = native_fn(vm, args);
        match result {
            Ok(HogValue::Ref(ptr)) => vm.push_stack(ptr),
            Ok(HogValue::Lit(lit)) => match lit {
                // Object types returned from native functions get heap allocated, just like ones declared
                // in the bytecode, whereas other types are pushed directly onto the stack. The purity of
                // native functions means we don't need to worry about memory management for these values,
                // beyond what the heap internally manages.
                HogLiteral::Array(_) | HogLiteral::Object(_) => {
                    let ptr = vm.heap.emplace(lit)?;
                    vm.push_stack(ptr)
                }
                _ => vm.push_stack(lit),
            },
            Err(e) => Err(e),
        }
    }

    pub fn get_bytecode(&self, ip: usize, symbol: &Option<Symbol>) -> Result<&JsonValue, VmError> {
        let res = match symbol {
            Some(symbol) => self
                .symbol_table
                .get(symbol)
                .ok_or_else(|| VmError::UnknownSymbol(symbol.to_string()))?
                .get(ip),
            None => self.program.get(ip),
        };

        res.ok_or(VmError::EndOfProgram(ip))
    }

    pub fn version(&self) -> u64 {
        self.program.version()
    }
}

impl Symbol {
    pub fn new(module: &str, name: &str) -> Self {
        Symbol {
            name: name.to_string(),
            module: module.to_string(),
        }
    }
}

impl std::fmt::Display for Symbol {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}/{}", self.module, self.name)
    }
}
