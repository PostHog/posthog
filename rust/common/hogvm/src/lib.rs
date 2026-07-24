// This lint suggests `ok_or(VmError::...)` over `ok_or_else(|| VmError::...)` when the error is
// "trivial" to build. On the interpreter's per-token fetch path that eager construction of the
// large VmError enum is a measured end-to-end regression, so the crate deliberately stays lazy
// everywhere on the hot path.
#![allow(clippy::unnecessary_lazy_evaluations)]

mod context;
mod error;
mod memory;
mod ops;
mod print;
mod program;
mod state;
mod stl;
mod util;
mod values;
mod vm;

// Execution context
pub use context::ExecutionContext;

// Programs and modules
pub use program::ExportedFunction;
pub use program::Module;
pub use program::Program;
pub use program::Token;

// VM, and helpers
pub use vm::sync_execute;
pub use vm::HogVM;
pub use vm::StepOutcome;
pub use vm::VmFailure;
pub use vm::MAX_JSON_SERDE_DEPTH;

// Suspend/resume (async-coroutine) execution and state serialization
pub use state::Resumable;
pub use state::VmSnapshot;
pub use vm::execute_resumable;
pub use vm::resume;

// Canonical value printing (the `print(...)` oracle), used by the parity harness
pub use print::escape_string;
pub use print::print_hog_string_output;
pub use print::print_hog_value;

// STL - again, we expose a lot, because we want to make it easy to extend this
pub use stl::hog_stl;
pub use stl::native_func;
pub use stl::stl;
pub use stl::stl_map;
pub use stl::NativeFunction;

// Values - We expose almost everything here for the sake of native function extension authors
pub use values::construct_free_standing;
pub use values::Callable;
pub use values::Closure;
pub use values::FromHogLiteral;
pub use values::FromHogRef;
pub use values::HogLiteral;
pub use values::HogMap;
pub use values::HogStr;
pub use values::HogValue;
pub use values::LocalCallable;
pub use values::Num;
pub use values::NumOp;

// Errors
pub use error::VmError;
