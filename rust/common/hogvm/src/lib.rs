mod context;
mod error;
mod memory;
mod ops;
mod stl;
mod util;
mod values;
mod vm;

// Execution context
pub use context::ExecutionContext;

// VM, and helpers
pub use vm::sync_execute;
pub use vm::HogVM;
pub use vm::StepOutcome;
pub use vm::VmFailure;

// STL - again, we expose a lot, because we want to make it easy to extend this
pub use stl::stl;
pub use stl::stl_map;
pub use stl::NativeFunction;

// Values - We expose almost everything here for the sake of native function extension authors
pub use values::Callable;
pub use values::Closure;
pub use values::FromHogLiteral;
pub use values::FromHogRef;
pub use values::HogLiteral;
pub use values::HogValue;
pub use values::LocalCallable;
pub use values::Num;
pub use values::NumOp;

// Errors
pub use error::VmError;
