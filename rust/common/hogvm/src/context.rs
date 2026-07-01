use once_cell::sync::Lazy;
use serde_json::{json, Value as JsonValue};
use std::collections::HashMap;
use std::sync::Arc;

use crate::{
    error::VmError,
    program::{ExportedFunction, Module, Program},
    stl::{hog_stl_map, stl_map, NativeFunction},
    vm::HogVM,
    HogLiteral, HogValue,
};

/// Default native-function and symbol tables, built once from the process-static STL and shared via
/// `Arc` by every [`ExecutionContext::with_defaults`] so the maps aren't rebuilt per context.
static DEFAULT_NATIVE_FNS: Lazy<Arc<HashMap<String, NativeFunction>>> =
    Lazy::new(|| Arc::new(stl_map()));
static DEFAULT_SYMBOL_TABLE: Lazy<Arc<HashMap<Symbol, ExportedFunction>>> =
    Lazy::new(|| Arc::new(flatten_modules(&hog_stl_map())));

/// Flatten imported modules into the symbol table the VM looks up by `Symbol{module, name}`. The
/// module name is the `module` half, matching the `Symbol::new("stl", …)` the VM builds at
/// `CallGlobal` (see `vm.rs`).
fn flatten_modules(modules: &HashMap<String, Module>) -> HashMap<Symbol, ExportedFunction> {
    let mut table = HashMap::new();
    for (name, module) in modules.iter() {
        for (fn_name, function) in module.functions().iter() {
            table.insert(Symbol::new(name, fn_name), function.clone());
        }
    }
    table
}

/// The read-only context for the virtual machine.
pub struct ExecutionContext {
    program: Program,
    // TODO - this could and should be borrowed, it's read-only anyway and often the most expensive bit of the context
    pub globals: JsonValue, // Generally an object, but can be anything really

    pub max_stack_depth: usize,
    pub max_heap_size: usize,
    pub max_steps: usize,
    /// Opt-in comparison semantics. `false` (the default) is the legacy/reference behavior shared by
    /// every existing consumer (e.g. `cymbal`): ordering ops require numeric operands and `Eq`
    /// compares temporals structurally. `true` makes ordering coerce across types and order temporals
    /// by epoch, and `Eq` compare two temporals by epoch — the ClickHouse/Python-TS-aligned semantics
    /// the realtime-cohort evaluator needs. Set via [`ExecutionContext::with_coercing_comparisons`].
    pub(crate) coerce_comparisons: bool,
    // `Arc`-shared so cloning a default context is a refcount bump, not a deep copy; mutators
    // copy-on-write via `Arc::make_mut`.
    native_fns: Arc<HashMap<String, NativeFunction>>,
    symbol_table: Arc<HashMap<Symbol, ExportedFunction>>, // Flattened symbol table of all imported hog modules
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
            coerce_comparisons: false,
            native_fns: Arc::new(native_fns),
            symbol_table: Arc::new(flatten_modules(&modules)),
        }
    }

    pub fn with_defaults(bytecode: Program) -> Self {
        // TODO - these limits are basically randomly chosen
        Self {
            program: bytecode,
            globals: json!({}),
            max_stack_depth: 128,
            max_heap_size: 1024 * 1024,
            max_steps: 10_000,
            coerce_comparisons: false,
            native_fns: DEFAULT_NATIVE_FNS.clone(),
            symbol_table: DEFAULT_SYMBOL_TABLE.clone(),
        }
    }

    pub fn with_ext_fn(mut self, name: String, func: NativeFunction) -> Self {
        Arc::make_mut(&mut self.native_fns).insert(name, func);
        self
    }

    pub fn with_ext_fns(mut self, fns: HashMap<String, NativeFunction>) -> Self {
        Arc::make_mut(&mut self.native_fns).extend(fns);
        self
    }

    pub fn set_fns(mut self, fns: HashMap<String, NativeFunction>) -> Self {
        self.native_fns = Arc::new(fns);
        self
    }

    pub fn with_globals(mut self, globals: JsonValue) -> Self {
        self.globals = globals;
        self
    }

    /// Swap globals in place (no clone) so one context can be reused across evaluations sharing them.
    pub fn set_globals(&mut self, globals: JsonValue) {
        self.globals = globals;
    }

    /// Swap the program in place to reuse one context across many programs (e.g. catalog conditions).
    pub fn set_program(&mut self, program: Program) {
        self.program = program;
    }

    /// Opt into coercing comparison semantics (cross-type ordering coercion + epoch ordering/equality
    /// of temporals). Off by default; only the realtime-cohort evaluator opts in, so existing
    /// consumers like `cymbal` keep the legacy strict behavior. See [`Self::coerce_comparisons`].
    pub fn with_coercing_comparisons(mut self) -> Self {
        self.coerce_comparisons = true;
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
        self.symbol_table = Arc::new(flatten_modules(modules));
        self
    }

    pub fn add_module(mut self, name: String, module: &Module) -> Self {
        let table = Arc::make_mut(&mut self.symbol_table);
        for (fn_name, function) in module.functions().iter() {
            table.insert(Symbol::new(&name, fn_name), function.clone());
        }
        self
    }

    pub fn to_vm(&self) -> Result<HogVM<'_>, VmError> {
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
        let emplaced = walk_emplacing(vm, native_fn(vm, args)?)?;
        vm.push_stack(emplaced)
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

/// Walk a HogValue and its children recursively to ensure all indexable types (arrays and objects) are heap allocated,
/// and then return the now-properly-allocated value. This is useful if, for example, you've constructed a HogValue
/// from a JSON object without mutable access to a VM's heap, and now need to push it into the VM's memory space for the
/// program to use.
///
/// This is exposed as a utility, but generally ExecutionContext::execute_native_function_call should do what you need.
fn walk_emplacing(vm: &mut HogVM, value: HogValue) -> Result<HogValue, VmError> {
    // Chase the pointer, if this is one, and clone out of it. We hold on to the original pointer
    // so we can swap the walked value back into it after we're done.
    let (literal, existing_location) = match value {
        HogValue::Lit(lit) => (lit, None),
        HogValue::Ref(ptr) => {
            let val = vm.heap.get(ptr)?.clone();
            (val, Some(ptr))
        }
    };

    match literal {
        HogLiteral::Array(arr) => {
            // Fast path: when every element is a plain (non-container, non-reference) literal there
            // is nothing to emplace, so skip the per-element walk + re-collect entirely. Native STL
            // results are overwhelmingly flat numeric/string arrays, and this walk was the single
            // hottest function in the interpreter (~25% of instructions) before this guard.
            let emplaced_arr = if arr.iter().all(is_flat_literal) {
                HogLiteral::Array(arr)
            } else {
                let walked: Result<Vec<HogValue>, _> =
                    arr.into_iter().map(|i| walk_emplacing(vm, i)).collect();
                HogLiteral::Array(walked?)
            };

            if let Some(ptr) = existing_location {
                // If this was already a heap-allocated array, replace it with the new one
                *vm.heap.get_mut(ptr)? = emplaced_arr;
                Ok(ptr.into())
            } else {
                // Otherwise heap allocate it and return the pointer
                vm.heap.emplace(emplaced_arr).map(|ptr| ptr.into())
            }
        }
        HogLiteral::Object(obj) => {
            let emplaced_obj: Result<HashMap<String, HogValue>, _> = obj
                .into_iter()
                .map(|(k, v)| Ok((k, walk_emplacing(vm, v)?)))
                .collect();
            let emplaced_obj = HogLiteral::Object(emplaced_obj?);

            if let Some(ptr) = existing_location {
                // As above, if this was already heap allocated, replace it with the new one
                *vm.heap.get_mut(ptr)? = emplaced_obj;
                Ok(ptr.into())
            } else {
                // Otherwise heap allocate it and return the pointer
                vm.heap.emplace(emplaced_obj).map(|ptr| ptr.into())
            }
        }
        // If we're looking at a non-indexable type, just return it, or the reference to it,
        // if it was already heap allocated.
        _ => Ok(existing_location
            .map(|ptr| ptr.into())
            .unwrap_or(literal.into())),
    }
}

// A value that needs no emplacing: a literal that isn't itself a nested container (so it holds no
// child values that must be hoisted onto the heap). References are excluded — they already point at
// heap state, but the walk preserves the original conservative behavior for them.
fn is_flat_literal(v: &HogValue) -> bool {
    matches!(
        v,
        HogValue::Lit(
            HogLiteral::Number(_)
                | HogLiteral::Boolean(_)
                | HogLiteral::String(_)
                | HogLiteral::Null
                | HogLiteral::Callable(_)
                | HogLiteral::Closure(_)
        )
    )
}
