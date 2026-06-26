//! Suspend/resume state serialization — the async-coroutine half of Node-VM parity.
//!
//! The reference VM (`@posthog/hogvm`) is a suspendable coroutine: when a program calls a registered
//! async function (`fetch`, `email`, …) it returns a fully-serializable `VMState`; the host performs
//! the side effect out-of-band (often across a queue) and resumes by re-entering with that state.
//! CDP hog functions (destinations) depend on this. This module is the Rust equivalent: snapshot the
//! live [`crate::vm::HogVM`] to a JSON-serializable [`VmSnapshot`] and rehydrate it.
//!
//! The encoding mirrors the reference's value shapes so the two can interoperate during migration:
//!   - the heap is flattened — `HogValue::Ref`s are resolved inline, exactly as the reference stores
//!     arrays/objects directly (JSON can't represent sharing anyway, except upvalues),
//!   - closures serialize as `{__hogClosure__, callable, upvalues: [id…]}`,
//!   - upvalues serialize as a flat `__hogUpValue__[]` keyed by `id`; the open/close sharing of
//!     Rust's `Rc<RefCell<Upvalue>>` graph is reconstructed from those ids on resume.
//!
//! Frame-level state (the call stack) is serialized in Rust-native form for now; see [`FrameJson`]
//! for the exact mapping required to reach byte-compatibility with the reference's per-frame
//! `{closure, ip, chunk}` layout.

use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

use indexmap::IndexMap;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value as JsonValue};

use crate::context::Symbol;
use crate::error::VmError;
use crate::memory::VmHeap;
use crate::values::{Callable, Closure, HogLiteral, HogValue, LocalCallable, Upvalue, UpvalueCell};

/// A serializable snapshot of a suspended VM. The program/STL live in the `ExecutionContext`, which
/// the host re-supplies on resume, so they are not part of the snapshot (the reference keeps
/// `bytecodes` here for wire transport; resuming against a known context makes that redundant).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VmSnapshot {
    /// The value stack, heap flattened, in reference value shapes.
    pub stack: Vec<JsonValue>,
    /// Hoisted upvalues, flat and keyed by `id`; closures reference these ids.
    pub upvalues: Vec<UpvalueJson>,
    /// The call stack (Rust-native form — see [`FrameJson`]).
    pub call_stack: Vec<FrameJson>,
    /// The try/catch stack.
    pub throw_stack: Vec<ThrowJson>,
    /// Instruction pointer of the active frame.
    pub ip: usize,
    /// The module the active frame is executing in (`None` == root program).
    pub chunk: Option<SymbolJson>,
    /// How many async suspensions have happened so far this run.
    pub async_steps: usize,
}

/// One hoisted upvalue. `closed` upvalues own their `value`; open ones read through `location` into
/// the live stack, so their `value` is `null`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpvalueJson {
    #[serde(rename = "__hogUpValue__")]
    pub marker: bool,
    pub id: usize,
    pub location: usize,
    pub closed: bool,
    pub value: JsonValue,
}

/// A call frame. Rust drives a single live `ip` plus a `ret_ptr` per pushed frame, whereas the
/// reference stores an `ip` (and full `closure`) in *every* frame including the active one. Mapping
/// to the reference layout means: the active reference frame's `ip` is the VM's live `ip`; each
/// parent reference frame's `ip` is the `ret_ptr` of the frame below it; and each frame's `closure`
/// must be reconstructed from `captures` + the callable metadata. That remap is the remaining step
/// for full wire-compatibility; the Rust-native form here round-trips losslessly within Rust.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FrameJson {
    pub ret_ptr: usize,
    pub ret_chunk: Option<SymbolJson>,
    pub stack_start: usize,
    /// Ids (into `upvalues`) of the cells this frame captured from its parent scope.
    pub captures: Vec<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThrowJson {
    pub catch_ptr: usize,
    pub catch_chunk: Option<SymbolJson>,
    pub stack_start: usize,
    pub call_depth: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SymbolJson {
    pub module: String,
    pub name: String,
}

impl SymbolJson {
    pub fn of(symbol: &Option<Symbol>) -> Option<Self> {
        symbol.as_ref().map(|s| SymbolJson {
            module: s.module.clone(),
            name: s.name.clone(),
        })
    }

    pub fn to_symbol(opt: &Option<SymbolJson>) -> Option<Symbol> {
        opt.as_ref().map(|s| Symbol::new(&s.module, &s.name))
    }
}

/// The result of driving a resumable execution: either the program finished, or it suspended on an
/// async call and handed back everything the host needs to perform the side effect and resume.
#[derive(Debug, Clone)]
pub enum Resumable {
    Finished(JsonValue),
    Suspended {
        function: String,
        args: Vec<JsonValue>,
        state: VmSnapshot,
    },
}

/// Interns `UpvalueCell`s by pointer identity so the shared `Rc<RefCell<Upvalue>>` graph serializes
/// to stable ids (mirroring the reference's `HogUpValue.id`).
#[derive(Default)]
pub struct CellRegistry {
    by_ptr: HashMap<usize, usize>,
    cells: Vec<UpvalueCell>,
}

impl CellRegistry {
    pub fn intern(&mut self, cell: &UpvalueCell) -> usize {
        let ptr = Rc::as_ptr(cell) as usize;
        if let Some(&id) = self.by_ptr.get(&ptr) {
            return id;
        }
        let id = self.cells.len();
        self.by_ptr.insert(ptr, id);
        self.cells.push(cell.clone());
        id
    }

    pub fn cells(&self) -> &[UpvalueCell] {
        &self.cells
    }
}

fn chunk_string(symbol: &Option<Symbol>) -> JsonValue {
    match symbol {
        Some(s) => json!(format!("{}/{}", s.module, s.name)),
        None => json!("root"),
    }
}

// ---- serialize: HogValue -> reference-shaped JSON --------------------------------------------

/// Walk a value (deref-ing through the heap) and intern every `UpvalueCell` reachable through any
/// closure it contains, so the flat upvalue array is complete before any value is serialized.
pub fn collect_cells(
    value: &HogValue,
    heap: &VmHeap,
    registry: &mut CellRegistry,
) -> Result<(), VmError> {
    match value.deref(heap)? {
        HogLiteral::Array(items) | HogLiteral::Tuple(items) => {
            for item in items {
                collect_cells(item, heap, registry)?;
            }
        }
        HogLiteral::Object(map) => {
            for v in map.values() {
                collect_cells(v, heap, registry)?;
            }
        }
        HogLiteral::Closure(closure) => {
            for cell in &closure.captures {
                registry.intern(cell);
            }
        }
        _ => {}
    }
    Ok(())
}

/// Drain the registry's worklist: every closed cell's owned value may itself hold closures, whose
/// cells must also be interned. Iterates by index because interning appends.
pub fn close_over_cells(heap: &VmHeap, registry: &mut CellRegistry) -> Result<(), VmError> {
    let mut i = 0;
    while i < registry.cells.len() {
        let snapshot = {
            let cell = registry.cells[i].borrow();
            if cell.closed {
                cell.value.clone()
            } else {
                None
            }
        };
        if let Some(value) = snapshot {
            collect_cells(&value, heap, registry)?;
        }
        i += 1;
    }
    Ok(())
}

pub fn value_to_json(
    value: &HogValue,
    heap: &VmHeap,
    registry: &mut CellRegistry,
) -> Result<JsonValue, VmError> {
    let lit = value.deref(heap)?;
    Ok(match lit {
        HogLiteral::Null => JsonValue::Null,
        HogLiteral::Boolean(b) => json!(b),
        HogLiteral::Number(n) => JsonValue::Number(n.clone().try_into()?),
        HogLiteral::String(s) => json!(s),
        HogLiteral::Array(items) => {
            let mut out = Vec::with_capacity(items.len());
            for item in items {
                out.push(value_to_json(item, heap, registry)?);
            }
            json!(out)
        }
        HogLiteral::Tuple(items) => {
            let mut out = Vec::with_capacity(items.len());
            for item in items {
                out.push(value_to_json(item, heap, registry)?);
            }
            // Reference duck-types tuples as arrays with a marker; keep a marker so restore can
            // distinguish them from plain arrays (tuple `typeof` and `(a, b)` printing depend on it).
            json!({ "__hogTuple__": true, "items": out })
        }
        HogLiteral::Object(map) => {
            let mut out = serde_json::Map::with_capacity(map.len());
            for (k, v) in map {
                out.insert(k.clone(), value_to_json(v, heap, registry)?);
            }
            JsonValue::Object(out)
        }
        HogLiteral::Callable(callable) => callable_to_json(callable),
        HogLiteral::Closure(closure) => {
            let ids: Vec<usize> = closure
                .captures
                .iter()
                .map(|cell| registry.intern(cell))
                .collect();
            json!({
                "__hogClosure__": true,
                "callable": callable_to_json(&closure.callable),
                "upvalues": ids,
            })
        }
    })
}

fn callable_to_json(callable: &Callable) -> JsonValue {
    match callable {
        Callable::Local(lc) => json!({
            "__hogCallable__": "local",
            "name": lc.name,
            "argCount": lc.stack_arg_count,
            "upvalueCount": lc.capture_count,
            "ip": lc.ip,
            "chunk": chunk_string(&lc.symbol),
        }),
        Callable::Stl(name) => json!({
            "__hogCallable__": "stl",
            "name": name,
            "argCount": 0,
            "upvalueCount": 0,
            "ip": 0,
            "chunk": JsonValue::Null,
        }),
    }
}

// ---- deserialize: reference-shaped JSON -> HogValue ------------------------------------------

/// Rebuild a value, re-emplacing containers into `heap` and resolving closure captures against the
/// already-created `cells`.
pub fn value_from_json(
    json: &JsonValue,
    heap: &mut VmHeap,
    cells: &[UpvalueCell],
) -> Result<HogValue, VmError> {
    match json {
        JsonValue::Null => Ok(HogLiteral::Null.into()),
        JsonValue::Bool(b) => Ok(HogLiteral::Boolean(*b).into()),
        JsonValue::Number(n) => Ok(HogLiteral::Number(n.clone().into()).into()),
        JsonValue::String(s) => Ok(HogLiteral::String(s.clone()).into()),
        JsonValue::Array(items) => {
            let mut out = Vec::with_capacity(items.len());
            for item in items {
                out.push(value_from_json(item, heap, cells)?);
            }
            Ok(heap.emplace(HogLiteral::Array(out))?.into())
        }
        JsonValue::Object(map) => object_from_json(map, heap, cells),
    }
}

fn object_from_json(
    map: &serde_json::Map<String, JsonValue>,
    heap: &mut VmHeap,
    cells: &[UpvalueCell],
) -> Result<HogValue, VmError> {
    if map.contains_key("__hogClosure__") {
        let callable = callable_from_json(&map["callable"])?;
        let ids = map
            .get("upvalues")
            .and_then(|v| v.as_array())
            .ok_or_else(|| VmError::Other("closure missing upvalues".to_string()))?;
        let mut captures = Vec::with_capacity(ids.len());
        for id in ids {
            let id = id
                .as_u64()
                .ok_or_else(|| VmError::Other("bad upvalue id".to_string()))?
                as usize;
            let cell = cells
                .get(id)
                .ok_or_else(|| VmError::Other(format!("upvalue id {id} out of range")))?;
            captures.push(cell.clone());
        }
        return Ok(HogLiteral::Closure(Closure { captures, callable }).into());
    }
    if map.contains_key("__hogCallable__") {
        return Ok(
            HogLiteral::Callable(callable_from_json(&JsonValue::Object(map.clone()))?).into(),
        );
    }
    if map.get("__hogTuple__").and_then(|v| v.as_bool()) == Some(true) {
        let items = map
            .get("items")
            .and_then(|v| v.as_array())
            .ok_or_else(|| VmError::Other("tuple missing items".to_string()))?;
        let mut out = Vec::with_capacity(items.len());
        for item in items {
            out.push(value_from_json(item, heap, cells)?);
        }
        return Ok(heap.emplace(HogLiteral::Tuple(out))?.into());
    }
    // A plain object (including reference duck-types like __hogDateTime__, which Rust also models as
    // marked objects) — preserve key order.
    let mut out = IndexMap::with_capacity(map.len());
    for (k, v) in map {
        out.insert(k.clone(), value_from_json(v, heap, cells)?);
    }
    Ok(heap.emplace(HogLiteral::Object(out))?.into())
}

fn callable_from_json(json: &JsonValue) -> Result<Callable, VmError> {
    let kind = json
        .get("__hogCallable__")
        .and_then(|v| v.as_str())
        .ok_or_else(|| VmError::Other("callable missing kind".to_string()))?;
    match kind {
        "stl" => Ok(Callable::Stl(str_field(json, "name")?)),
        _ => {
            let chunk = json.get("chunk").and_then(|v| v.as_str());
            let symbol = chunk.and_then(|c| {
                if c == "root" {
                    None
                } else {
                    c.split_once('/').map(|(m, n)| Symbol::new(m, n))
                }
            });
            Ok(Callable::Local(LocalCallable {
                name: str_field(json, "name")?,
                stack_arg_count: usize_field(json, "argCount")?,
                capture_count: usize_field(json, "upvalueCount")?,
                ip: usize_field(json, "ip")?,
                symbol,
            }))
        }
    }
}

/// Build the flat upvalue cells from the snapshot in two passes: create empty cells first (so closure
/// captures can resolve by id), then fill each closed cell's owned value.
pub fn rebuild_cells(
    upvalues: &[UpvalueJson],
    heap: &mut VmHeap,
) -> Result<Vec<UpvalueCell>, VmError> {
    let cells: Vec<UpvalueCell> = upvalues
        .iter()
        .map(|uv| {
            Rc::new(RefCell::new(Upvalue {
                location: uv.location,
                closed: uv.closed,
                value: None,
            }))
        })
        .collect();

    for (uv, cell) in upvalues.iter().zip(cells.iter()) {
        if uv.closed {
            let value = value_from_json(&uv.value, heap, &cells)?;
            cell.borrow_mut().value = Some(value);
        }
    }
    Ok(cells)
}

fn str_field(json: &JsonValue, key: &str) -> Result<String, VmError> {
    json.get(key)
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .ok_or_else(|| VmError::Other(format!("missing string field '{key}'")))
}

fn usize_field(json: &JsonValue, key: &str) -> Result<usize, VmError> {
    json.get(key)
        .and_then(|v| v.as_u64())
        .map(|n| n as usize)
        .ok_or_else(|| VmError::Other(format!("missing numeric field '{key}'")))
}
