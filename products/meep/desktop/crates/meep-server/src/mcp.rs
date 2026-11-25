//! JSON-RPC methods shared by the authenticated topic and view tool endpoints.
use axum::{
    Json,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use serde_json::{Value, json};

pub(super) fn tool(name: &str, description: &str, properties: Value, required: &[&str]) -> Value {
    json!({"name":name,"description":description,"inputSchema":{"type":"object","properties":properties,"required":required,"additionalProperties":false}})
}

pub(super) async fn respond<T: serde::Serialize, I: serde::Serialize>(
    req: &Value,
    name: &str,
    instructions: impl FnOnce() -> I,
    tools: impl FnOnce() -> T,
    call: impl AsyncFnOnce(&str, &Value) -> Result<String, String>,
) -> Response {
    let rid = &req["id"];
    let error = |code: i32, message: &str| {
        Json(json!({"jsonrpc":"2.0","id":rid,"error":{"code":code,"message":message}}))
            .into_response()
    };
    let Some(method) = req["method"].as_str().filter(|_| req["jsonrpc"] == "2.0") else {
        return error(-32600, "Invalid JSON-RPC request");
    };
    if rid.is_null() {
        return StatusCode::ACCEPTED.into_response();
    }
    let result = match method {
        "initialize" => {
            let protocol = req["params"]["protocolVersion"]
                .as_str()
                .filter(|v| matches!(*v, "2025-03-26" | "2025-06-18" | "2025-11-25"))
                .unwrap_or("2025-11-25");
            json!({"protocolVersion":protocol,"capabilities":{"tools":{}},"serverInfo":{"name":name,"version":env!("CARGO_PKG_VERSION")},"instructions":instructions()})
        }
        "ping" => json!({}),
        "tools/list" => json!({"tools":tools()}),
        "tools/call" => {
            let result = call(
                req["params"]["name"].as_str().unwrap_or_default(),
                &req["params"]["arguments"],
            )
            .await;
            let failed = result.is_err();
            let text = result.unwrap_or_else(|message| message);
            json!({"isError":failed,"content":[{"type":"text","text":text}]})
        }
        _ => return error(-32601, "Method not found"),
    };
    Json(json!({"jsonrpc":"2.0","id":rid,"result":result})).into_response()
}
