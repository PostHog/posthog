//! Suspend/resume state serialization — the async-coroutine half of Node-VM parity.
//!
//! The reference VM (`@posthog/hogvm`) is a suspendable coroutine: when a program calls a registered
//! async function (`fetch`, `email`, `sleep`) it returns a fully-serializable `VMState`; the host
//! performs the side effect out-of-band (often across a queue) and resumes by re-entering with that
//! state. CDP hog functions (destinations) depend on this. This module snapshots the live
//! [`crate::vm::HogVM`] to a [`VmSnapshot`] whose JSON is **byte-compatible with the reference's
//! `VMState`**, so the two VMs can resume each other's states during migration.
//!
//! Shape decisions that mirror the reference:
//!   - the heap is flattened (`HogValue::Ref`s resolved inline; JSON can't share anyway),
//!   - closures serialize as `{__hogClosure__, callable, upvalues: [id…]}`,
//!   - upvalues are a flat `__hogUpValue__[]` keyed by `id` and **sorted by location** (the
//!     reference keeps `sortedUpValues` sorted so its capture early-break stays correct on resume),
//!   - the call stack carries a per-frame `{closure, ip, chunk, stackStart, argCount}` with an
//!     explicit root frame, and `ip` is header-inclusive for the root chunk (see [`VmSnapshot`]).

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

/// A snapshot of a suspended VM, serializing to the reference VM's `VMState` JSON. Field names match
/// the reference (camelCase) so a state produced here can be resumed by Node and vice versa.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VmSnapshot {
    /// The chunk map — `{ "root": { "bytecode": [...] } }` (globals are re-supplied via options on
    /// resume, matching the reference). Carried for wire compatibility; Rust resume ignores it and
    /// uses the supplied `ExecutionContext` instead.
    pub bytecodes: JsonValue,
    /// The value stack, heap flattened, in reference value shapes.
    pub stack: Vec<JsonValue>,
    /// Hoisted upvalues, flat, sorted by location, each carrying its `id`; closures reference ids.
    pub upvalues: Vec<UpvalueJson>,
    /// The call stack, root frame first, active frame last (never empty).
    #[serde(rename = "callStack")]
    pub call_stack: Vec<CallFrameJson>,
    #[serde(rename = "throwStack")]
    pub throw_stack: Vec<ThrowFrameJson>,
    /// Deprecated reference field; always empty here.
    #[serde(rename = "declaredFunctions")]
    pub declared_functions: JsonValue,
    pub ops: usize,
    #[serde(rename = "asyncSteps")]
    pub async_steps: usize,
    #[serde(rename = "syncDuration")]
    pub sync_duration: u64,
    #[serde(rename = "maxMemUsed")]
    pub max_mem_used: usize,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub telemetry: Option<Vec<JsonValue>>,
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

/// A call frame in the reference's layout: the `closure` running in this frame, its current `ip`
/// (header-inclusive for the root chunk), the `chunk` (module) it runs in, where its stack window
/// starts, and how many args it was called with.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CallFrameJson {
    pub closure: JsonValue,
    pub ip: usize,
    pub chunk: String,
    #[serde(rename = "stackStart")]
    pub stack_start: usize,
    #[serde(rename = "argCount")]
    pub arg_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThrowFrameJson {
    #[serde(rename = "callStackLen")]
    pub call_stack_len: usize,
    #[serde(rename = "stackLen")]
    pub stack_len: usize,
    #[serde(rename = "catchIp")]
    pub catch_ip: usize,
}

/// The result of driving a resumable execution: either the program finished, or it suspended on an
/// async call and handed back everything the host needs to perform the side effect and resume.
#[derive(Debug, Clone)]
pub enum Resumable {
    Finished(JsonValue),
    Suspended {
        function: String,
        args: Vec<JsonValue>,
        // Boxed: the snapshot is much larger than the `Finished` variant, so keep the enum small.
        state: Box<VmSnapshot>,
    },
}

/// Interns `UpvalueCell`s by pointer identity so the shared `Rc<RefCell<Upvalue>>` graph serializes
/// to stable ids (mirroring the reference's `HogUpValue.id`). Ids are assigned in intern order.
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

// ---- chunk <-> symbol -------------------------------------------------------------------------

/// Render a module as a reference chunk name: `None` (the top-level program) is `"root"`; an STL or
/// imported module symbol is `"module/name"`.
pub fn chunk_str(symbol: &Option<Symbol>) -> String {
    match symbol {
        None => "root".to_string(),
        Some(s) => format!("{}/{}", s.module, s.name),
    }
}

/// Inverse of [`chunk_str`].
pub fn chunk_to_symbol(chunk: &str) -> Option<Symbol> {
    if chunk == "root" {
        return None;
    }
    chunk.split_once('/').map(|(m, n)| Symbol::new(m, n))
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
    header_len: usize,
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
                out.push(value_to_json(item, heap, registry, header_len)?);
            }
            json!(out)
        }
        HogLiteral::Tuple(items) => {
            let mut out = Vec::with_capacity(items.len());
            for item in items {
                out.push(value_to_json(item, heap, registry, header_len)?);
            }
            // The reference duck-types tuples as arrays with a marker; keep one so restore can tell
            // them apart (tuple `typeof` and `(a, b)` printing depend on it).
            json!({ "__hogTuple__": true, "items": out })
        }
        HogLiteral::Object(map) => {
            let mut out = serde_json::Map::with_capacity(map.len());
            for (k, v) in map {
                out.insert(k.clone(), value_to_json(v, heap, registry, header_len)?);
            }
            JsonValue::Object(out)
        }
        HogLiteral::Callable(callable) => callable_to_json(callable, header_len),
        HogLiteral::Closure(closure) => closure_to_json(closure, registry, header_len),
    })
}

pub fn closure_to_json(
    closure: &Closure,
    registry: &mut CellRegistry,
    header_len: usize,
) -> JsonValue {
    // Upvalue ids are 1-based to match the reference (`id: sortedUpValues.length + 1`).
    let ids: Vec<usize> = closure
        .captures
        .iter()
        .map(|cell| registry.intern(cell) + 1)
        .collect();
    json!({
        "__hogClosure__": true,
        "callable": callable_to_json(&closure.callable, header_len),
        "upvalues": ids,
    })
}

fn callable_to_json(callable: &Callable, header_len: usize) -> JsonValue {
    match callable {
        Callable::Local(lc) => {
            // The reference's callable ip is header-inclusive for the root chunk; module callables
            // carry no header. Our `ip` is body-relative, so add the header for root-chunk callables.
            let ip = lc.ip + if lc.symbol.is_none() { header_len } else { 0 };
            json!({
                "__hogCallable__": "local",
                "name": lc.name,
                "argCount": lc.stack_arg_count,
                "upvalueCount": lc.capture_count,
                "ip": ip,
                "chunk": chunk_str(&lc.symbol),
            })
        }
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

/// The reference's synthetic root-frame closure (an empty local callable in chunk `root`).
pub fn root_closure_json() -> JsonValue {
    json!({
        "__hogClosure__": true,
        "callable": {
            "__hogCallable__": "local",
            "name": "",
            "argCount": 0,
            "upvalueCount": 0,
            "ip": 1,
            "chunk": "root",
        },
        "upvalues": [],
    })
}

// ---- deserialize: reference-shaped JSON -> HogValue ------------------------------------------

/// Rebuild a value, re-emplacing containers into `heap` and resolving closure captures against the
/// already-created `cells` (keyed by id).
pub fn value_from_json(
    json: &JsonValue,
    heap: &mut VmHeap,
    cells: &HashMap<usize, UpvalueCell>,
    header_len: usize,
) -> Result<HogValue, VmError> {
    match json {
        JsonValue::Null => Ok(HogLiteral::Null.into()),
        JsonValue::Bool(b) => Ok(HogLiteral::Boolean(*b).into()),
        JsonValue::Number(n) => Ok(HogLiteral::Number(n.clone().into()).into()),
        JsonValue::String(s) => Ok(HogLiteral::String(s.clone()).into()),
        JsonValue::Array(items) => {
            let mut out = Vec::with_capacity(items.len());
            for item in items {
                out.push(value_from_json(item, heap, cells, header_len)?);
            }
            Ok(heap.emplace(HogLiteral::Array(out))?.into())
        }
        JsonValue::Object(map) => object_from_json(map, heap, cells, header_len),
    }
}

fn object_from_json(
    map: &serde_json::Map<String, JsonValue>,
    heap: &mut VmHeap,
    cells: &HashMap<usize, UpvalueCell>,
    header_len: usize,
) -> Result<HogValue, VmError> {
    if map.contains_key("__hogClosure__") {
        return Ok(HogLiteral::Closure(closure_from_json(
            &JsonValue::Object(map.clone()),
            cells,
            header_len,
        )?)
        .into());
    }
    if map.contains_key("__hogCallable__") {
        return Ok(HogLiteral::Callable(callable_from_json(
            &JsonValue::Object(map.clone()),
            header_len,
        )?)
        .into());
    }
    if map.get("__hogTuple__").and_then(|v| v.as_bool()) == Some(true) {
        let items = map
            .get("items")
            .and_then(|v| v.as_array())
            .ok_or_else(|| VmError::Other("tuple missing items".to_string()))?;
        let mut out = Vec::with_capacity(items.len());
        for item in items {
            out.push(value_from_json(item, heap, cells, header_len)?);
        }
        return Ok(heap.emplace(HogLiteral::Tuple(out))?.into());
    }
    // A plain object (including reference duck-types like __hogDateTime__, which Rust also models as
    // marked objects) — preserve key order.
    let mut out = IndexMap::with_capacity(map.len());
    for (k, v) in map {
        out.insert(k.clone(), value_from_json(v, heap, cells, header_len)?);
    }
    Ok(heap.emplace(HogLiteral::Object(out))?.into())
}

pub fn closure_from_json(
    json: &JsonValue,
    cells: &HashMap<usize, UpvalueCell>,
    header_len: usize,
) -> Result<Closure, VmError> {
    let callable = callable_from_json(
        json.get("callable")
            .ok_or_else(|| VmError::Other("closure missing callable".to_string()))?,
        header_len,
    )?;
    let ids = json
        .get("upvalues")
        .and_then(|v| v.as_array())
        .ok_or_else(|| VmError::Other("closure missing upvalues".to_string()))?;
    let mut captures = Vec::with_capacity(ids.len());
    for id in ids {
        let id = id
            .as_u64()
            .ok_or_else(|| VmError::Other("bad upvalue id".to_string()))? as usize;
        let cell = cells
            .get(&id)
            .ok_or_else(|| VmError::Other(format!("upvalue id {id} not found")))?;
        captures.push(cell.clone());
    }
    Ok(Closure { captures, callable })
}

fn callable_from_json(json: &JsonValue, header_len: usize) -> Result<Callable, VmError> {
    let kind = json
        .get("__hogCallable__")
        .and_then(|v| v.as_str())
        .ok_or_else(|| VmError::Other("callable missing kind".to_string()))?;
    match kind {
        "stl" => Ok(Callable::Stl(str_field(json, "name")?)),
        _ => {
            let chunk = json.get("chunk").and_then(|v| v.as_str()).unwrap_or("root");
            // Inverse of the serialize-side header offset: root-chunk ips are header-inclusive.
            let offset = if chunk == "root" { header_len } else { 0 };
            Ok(Callable::Local(LocalCallable {
                name: str_field(json, "name")?,
                stack_arg_count: usize_field(json, "argCount")?,
                capture_count: usize_field(json, "upvalueCount")?,
                ip: usize_field(json, "ip")?.saturating_sub(offset),
                symbol: chunk_to_symbol(chunk),
            }))
        }
    }
}

/// Build the flat upvalue cells from the snapshot, keyed by id, in two passes: create empty cells
/// first (so closure captures resolve by id), then fill each closed cell's owned value.
pub fn rebuild_cells(
    upvalues: &[UpvalueJson],
    heap: &mut VmHeap,
    header_len: usize,
) -> Result<HashMap<usize, UpvalueCell>, VmError> {
    let mut cells: HashMap<usize, UpvalueCell> = HashMap::with_capacity(upvalues.len());
    for uv in upvalues {
        cells.insert(
            uv.id,
            Rc::new(RefCell::new(Upvalue {
                location: uv.location,
                closed: uv.closed,
                value: None,
            })),
        );
    }
    for uv in upvalues {
        if uv.closed {
            let value = value_from_json(&uv.value, heap, &cells, header_len)?;
            cells[&uv.id].borrow_mut().value = Some(value);
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
