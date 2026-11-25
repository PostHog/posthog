//! Browser JavaScript backend. The real SDK and fixed view execute in one
//! per-view closure; none of their bindings are installed on the page global.
use crate::script_engine::{HostQueue, ScriptEngine};
use js_sys::{Array, Function, Object, Reflect};
use serde_json::Value;
use std::{cell::RefCell, collections::VecDeque, rc::Rc};
use wasm_bindgen::{JsCast, prelude::*};

type Bridge = dyn Fn(String, String, String, String) -> Result<String, JsValue>;

pub struct Engine {
    api: JsValue,
    _bridge: Closure<Bridge>,
    wake: RefCell<Option<Closure<dyn Fn()>>>,
    pub data: Rc<RefCell<crate::datasets::Datasets>>,
    pub scenes: Rc<RefCell<crate::scene::Scenes>>,
    pub logs: Rc<RefCell<VecDeque<String>>>,
    queue: Rc<RefCell<HostQueue>>,
}
fn error(value: JsValue) -> String {
    Reflect::get(&value, &"stack".into())
        .ok()
        .and_then(|v| v.as_string())
        .or_else(|| value.as_string())
        .unwrap_or_else(|| format!("{value:?}"))
}
impl Engine {
    pub fn new(source: &str, saved: &Value) -> Result<Self, String> {
        let data = Rc::new(RefCell::new(crate::datasets::Datasets::default()));
        let scenes = Rc::new(RefCell::new(crate::scene::Scenes::default()));
        let logs = Rc::new(RefCell::new(VecDeque::new()));
        let queue = Rc::new(RefCell::new(HostQueue::default()));
        let (d, l, q) = (data.clone(), logs.clone(), queue.clone());
        let bridge = Closure::wrap(Box::new(
            move |kind: String, a: String, b: String, c: String| -> Result<String, JsValue> {
                let result: Result<String, String> = (|| {
                    match kind.as_str() {
                        "dirty" => q.borrow_mut().dirty = true,
                        "request" | "local" => {
                            let mut queue = q.borrow_mut();
                            if !queue.reserve(a.len() + b.len() + c.len()) {
                                return Err("Host queue limit exceeded".into());
                            }
                            if kind == "request" {
                                queue.requests.push((
                                    a.parse().map_err(|_| "Invalid request id")?,
                                    b,
                                    c.parse().map_err(|_| "Invalid host parameters")?,
                                ));
                            } else {
                                queue
                                    .local
                                    .push((a, b.parse().map_err(|_| "Invalid effect")?));
                            }
                        }
                        "data" => {
                            let result = d.borrow_mut().request_owned(
                                &a,
                                &b,
                                c.parse().map_err(|_| "Invalid dataset arguments")?,
                            )?;
                            if matches!(a.as_str(), "set" | "patch" | "remove" | "clear") {
                                q.borrow_mut().dirty = true;
                            }
                            return Ok(result.to_string());
                        }
                        "markdown" => {
                            use crate::block_editor::{markdown, model::Doc};
                            return Ok(if a == "to" {
                                markdown::to_markdown(
                                    &Doc::from_json(&b.parse().map_err(|_| "Invalid blocks")?)
                                        .blocks,
                                )
                            } else {
                                Doc::new(markdown::from_markdown(&b)).to_json().to_string()
                            });
                        }
                        "log" => {
                            let mut logs = l.borrow_mut();
                            if logs.len() == 50 {
                                logs.pop_front();
                            }
                            logs.push_back(a.chars().take(2000).collect());
                        }
                        _ => return Err(format!("{kind} is unavailable in the web preview")),
                    }
                    Ok("null".into())
                })();
                result.map_err(|e| js_sys::Error::new(&e).into())
            },
        )
            as Box<dyn Fn(String, String, String, String) -> Result<String, JsValue>>);
        let body = format!(
            r#"
const globalThis = Object.create(null);
let wake = () => {{}}, scheduled = false, retired = false;
const changed = () => {{ if (!retired && !scheduled) {{ scheduled = true; Promise.resolve().then(() => {{ scheduled = false; wake(); }}); }} }};
const __host_dirty = () => {{ bridge('dirty','','',''); changed(); }};
const __host_request = (id, method, params) => {{ bridge('request',String(id),method,params); changed(); }};
const __host_local = (kind, value) => {{ bridge('local',kind,value,''); changed(); }};
const __host_data = (op,name,args) => {{ const result = bridge('data',op,name,args); changed(); return result; }};
const __host_scene = () => {{ throw new Error('Scene ingestion is unavailable in the web preview'); }};
const __host_markdown = (op,text) => bridge('markdown',op,text,'');
const __host_log = text => bridge('log',text,'','');
Object.assign(globalThis, {{__host_dirty,__host_request,__host_local}});
{}
{}
{}
__ready();
return {{ __render, __row, __cell, __invoke, __key, __init, __settle, __fire, __boot, __checkpoint, __badge, __badge_end, setWake: f => {{ wake = f; }}, retire: () => {{
  retired = true; wake = () => {{}}; bridge = () => 'null';
  __pending.clear(); __timers.clear();
}} }};
"#,
            include_str!("script_prelude.js"),
            include_str!("script_agents.js"),
            source
        );
        let api = Function::new_with_args("bridge", &body)
            .call1(&JsValue::UNDEFINED, bridge.as_ref())
            .map_err(error)?;
        let engine = Self {
            api,
            _bridge: bridge,
            wake: RefCell::new(None),
            data,
            scenes,
            logs,
            queue,
        };
        engine.call("__boot", &[saved.to_string().into()])?;
        Ok(engine)
    }
    /// Sever retained JS microtasks from Rust before dropping a generation.
    pub fn retire(&self) {
        let _ = self.call("retire", &[]);
    }
    pub fn set_wake(&self, callback: impl Fn() + 'static) {
        let wake = Closure::wrap(Box::new(callback) as Box<dyn Fn()>);
        self.call("setWake", &[wake.as_ref().clone()])
            .expect("wake callback");
        *self.wake.borrow_mut() = Some(wake);
    }
    fn call(&self, name: &str, args: &[JsValue]) -> Result<JsValue, String> {
        let f: Function = Reflect::get(&self.api, &name.into())
            .map_err(error)?
            .dyn_into()
            .map_err(error)?;
        let array = Array::new();
        for arg in args {
            array.push(arg);
        }
        f.apply(&Object::new(), &array).map_err(error)
    }
    fn json(&self, name: &str, args: &[JsValue]) -> Result<Value, String> {
        self.call(name, args)?
            .as_string()
            .ok_or_else(|| format!("{name} did not return JSON"))?
            .parse()
            .map_err(|e| format!("{e}"))
    }
    pub fn checkpoint(&self) -> Result<Value, String> {
        self.json("__checkpoint", &[])
    }
    /// The sidebar count and, when badge() returned an object with a title or
    /// items, that object for the row's hover card.
    pub fn badge(&self) -> Result<(Option<String>, Option<Value>), String> {
        let before = self.checkpoint()?.to_string();
        self.data.borrow_mut().read_only = true;
        let value = self.json("__badge", &[before.clone().into()]);
        self.data.borrow_mut().read_only = false;
        let changed = self
            .call("__badge_end", &[before.into()])?
            .as_bool()
            .unwrap_or(true);
        if changed {
            return Err("badge() must not change state".into());
        }
        let value = value?;
        let card = (value.get("title").is_some_and(Value::is_string)
            || value["items"]
                .as_array()
                .is_some_and(|items| !items.is_empty()))
        .then(|| value.clone());
        Ok((crate::design::badge_text(value), card))
    }
    pub fn take_queue(&self) -> HostQueue {
        std::mem::take(&mut self.queue.borrow_mut())
    }
}
impl Drop for Engine {
    fn drop(&mut self) {
        self.retire();
    }
}
impl ScriptEngine for Engine {
    fn render(&self) -> Result<Value, String> {
        self.json("__render", &[])
    }
    fn row(&self, function: u32, index: usize) -> Result<Value, String> {
        self.json("__row", &[function.into(), (index as u32).into()])
    }
    fn cell(&self, function: u32, row: &Value) -> Result<Value, String> {
        self.json("__cell", &[function.into(), row.to_string().into()])
    }
    fn invoke(&self, handler: u32, argument: &Value) -> Result<(), String> {
        self.call("__invoke", &[handler.into(), argument.to_string().into()])
            .map(|_| ())
    }
    fn key(&self, name: &str) -> Result<bool, String> {
        Ok(self
            .call("__key", &[name.into()])?
            .as_bool()
            .unwrap_or(false))
    }
    fn init(&self) -> Result<(), String> {
        self.call("__init", &[]).map(|_| ())
    }
    fn settle(&self, id: u32, result: Result<Value, String>) -> Result<(), String> {
        let (ok, text) = match result {
            Ok(v) => (true, v.to_string()),
            Err(e) => (false, e),
        };
        self.call("__settle", &[id.into(), ok.into(), text.into()])
            .map(|_| ())
    }
    fn fire(&self, timer: u64) -> Result<(), String> {
        self.call("__fire", &[(timer as f64).into()]).map(|_| ())
    }
}
