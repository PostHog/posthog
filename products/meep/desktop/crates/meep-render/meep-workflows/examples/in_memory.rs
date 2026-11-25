//! Resolve a workflow against a host-owned counter and checkpoint the result.
use meep_workflows::{
    HostError, Workflow,
    runner::{self, Control, Host, LocalFuture},
};
use serde_json::{Value, json};
use std::cell::RefCell;

#[derive(Default)]
struct Counter {
    state: RefCell<Value>,
    allow_next: bool,
}

impl Host for Counter {
    fn state(&self) -> runner::Result<Value> {
        Ok(self.state.borrow().clone())
    }

    fn patch(&self, value: Value) -> runner::Result<()> {
        let mut state = self.state.borrow_mut();
        for (key, field) in value.as_object().ok_or("Expected a state patch")? {
            state[key] = field.clone();
        }
        Ok(())
    }

    fn data(&self, _: &str, _: &str, _: Value) -> runner::Result<Value> {
        Err("This host has no datasets".into())
    }

    fn transform(&self, _: &str, _: Value) -> runner::Result<Value> {
        Err("This host has no custom transforms".into())
    }

    fn request(&self, method: &str, args: Value) -> LocalFuture<'_, Result<Value, HostError>> {
        let allowed =
            method == "sources.call" && args["source"] == "counter" && args["tool"] == "next";
        Box::pin(async move {
            if allowed && self.allow_next {
                Ok(json!(
                    self.state.borrow()["count"].as_u64().unwrap_or_default() + 1
                ))
            } else {
                Err("Counter denied this operation".into())
            }
        })
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> anyhow::Result<()> {
    let flow = Workflow::parse(json!({
        "version": 2, "id": "increment", "title": "Increment", "trigger": {"kind":"manual"},
        "steps": [
            {"id":"next", "kind":"source", "source":"counter", "tool":"next", "arguments":{}},
            {"id":"save", "kind":"state", "patch":{"count":{"$ref":"/steps/next"}}}
        ]
    }))?;
    let denied = Counter::default();
    let result = runner::run(&denied, &flow, Value::Null, Control::default())
        .await
        .result;
    anyhow::ensure!(result.unwrap_err().contains("denied") && denied.state.borrow().is_null());
    let counter = Counter {
        allow_next: true,
        ..Default::default()
    };
    let cancelled = Control::default();
    cancelled.cancel();
    let result = runner::run(&counter, &flow, Value::Null, cancelled)
        .await
        .result;
    anyhow::ensure!(result.unwrap_err().contains("cancelled") && counter.state.borrow().is_null());
    runner::run(&counter, &flow, Value::Null, Control::default())
        .await
        .result
        .map_err(anyhow::Error::msg)?;
    let state = counter.state().map_err(anyhow::Error::msg)?;
    anyhow::ensure!(state == json!({"count": 1}), "Unexpected counter value");
    println!("{state}");
    Ok(())
}
