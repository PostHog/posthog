use serde_json::{Value, json};
use std::{thread, time::Duration};
use tiny_http::{Header, Response, Server};

pub struct Step {
    method: &'static str,
    params: Value,
    result: Value,
    status: u16,
    event_query: bool,
}

impl Step {
    pub fn list(tools: &[&str]) -> Self {
        let tools = tools.iter().map(|name|json!({"name":name,"inputSchema":{"type":"object","properties":{"output_format":{"type":"string"}}}})).collect::<Vec<_>>();
        Self {
            method: "tools/list",
            params: json!({}),
            result: json!({"tools":tools}),
            status: 200,
            event_query: false,
        }
    }
    pub fn call(name: &str, args: Value, data: Value) -> Self {
        Self {
            method: "tools/call",
            params: json!({"name":name,"arguments":args}),
            result: json!({"structuredContent":data,"content":[]}),
            status: 200,
            event_query: false,
        }
    }
    pub fn event_query(mut self) -> Self {
        self.event_query = true;
        self
    }
    pub fn text(mut self, text: &str) -> Self {
        self.result = json!({"content":[{"type":"text","text":text}]});
        self
    }
    pub fn fail(mut self, status: u16) -> Self {
        self.status = status;
        self
    }
    pub fn page(mut self, cursor: &str) -> Self {
        self.result["nextCursor"] = json!(cursor);
        self
    }
    pub fn after(mut self, cursor: &str) -> Self {
        self.params["cursor"] = json!(cursor);
        self
    }
    pub fn rpc_error(mut self) -> Self {
        self.status = 0;
        self
    }
}

pub struct McpServer {
    pub endpoint: String,
    worker: thread::JoinHandle<()>,
}

impl McpServer {
    pub fn start(steps: Vec<Step>) -> Self {
        let server = Server::http("127.0.0.1:0").unwrap();
        let endpoint = format!("http://{}/mcp", server.server_addr());
        let worker = thread::spawn(move || {
            let mut steps = steps.into_iter().peekable();
            let mut session = 0;
            let mut initialized = false;
            let mut last_id = 0;
            let mut responses = 0;
            while steps.peek().is_some() {
                let mut request = server
                    // Give retry/backoff and a loaded development machine time
                    // to deliver the next request without losing the fixture.
                    .recv_timeout(Duration::from_secs(30))
                    .unwrap()
                    .expect("expected MCP request");
                assert_eq!(request.url(), "/mcp?project_id=17");
                assert_eq!(request.method().as_str(), "POST");
                let mut body = String::new();
                request.as_reader().read_to_string(&mut body).unwrap();
                let message: Value = serde_json::from_str(&body).unwrap();
                assert_eq!(message["jsonrpc"], "2.0");
                let header = |name| {
                    request
                        .headers()
                        .iter()
                        .find(|h| h.field.equiv(name))
                        .map(|h| h.value.as_str())
                };
                assert_eq!(header("authorization"), Some("Bearer test-token"));
                assert_eq!(header("x-posthog-mcp-mode"), Some("tools"));
                let accept = header("accept").unwrap();
                assert!(
                    accept.contains("application/json") && accept.contains("text/event-stream")
                );
                let method = message["method"].as_str().unwrap();
                let (status, result) = if method == "initialize" {
                    session += 1;
                    initialized = false;
                    last_id = 0;
                    assert_eq!(header("mcp-session-id"), None);
                    assert!(message["params"]["clientInfo"]["name"].is_string());
                    (
                        200,
                        json!({"protocolVersion":"2025-06-18","capabilities":{"tools":{}},"serverInfo":{"name":"test","version":"1"}}),
                    )
                } else {
                    assert!(session > 0);
                    assert_eq!(
                        header("mcp-session-id"),
                        Some(format!("session-{session}").as_str())
                    );
                    assert_eq!(header("mcp-protocol-version"), Some("2025-06-18"));
                    if method == "notifications/initialized" {
                        assert!(!initialized && message.get("id").is_none());
                        initialized = true;
                        request.respond(Response::empty(202)).unwrap();
                        continue;
                    }
                    assert!(initialized);
                    let step = steps.next().unwrap();
                    assert_eq!(method, step.method);
                    if step.event_query {
                        let actual = message["params"]["arguments"]["query"].as_str().unwrap();
                        let base = step.params["arguments"]["query"].as_str().unwrap();
                        let suffix = actual
                            .strip_prefix(&format!("{base} AND "))
                            .expect("event query");
                        let (left, right) = suffix.split_once(" = ").expect("cache bucket");
                        let bucket: i64 = left.parse().expect("numeric cache bucket");
                        assert_eq!(right, left);
                        assert!(
                            (chrono::Utc::now().timestamp().div_euclid(30) - bucket).abs() <= 1
                        );
                        let mut normalized = message["params"].clone();
                        normalized["arguments"]["query"] = json!(base);
                        assert_eq!(normalized, step.params);
                    } else {
                        assert_eq!(message["params"], step.params);
                    }
                    (step.status, step.result)
                };
                let id = message["id"].as_u64().unwrap();
                assert!(id > last_id);
                last_id = id;
                let rpc = if status > 0 && status < 300 {
                    json!({"jsonrpc":"2.0","id":id,"result":result})
                } else {
                    json!({"jsonrpc":"2.0","id":id,"error":{"code":-32602,"message":"upstream detail"}})
                };
                responses += 1;
                let (ctype, body) = if responses % 2 == 0 && status == 200 {
                    (
                        "text/event-stream",
                        format!(
                            ": keepalive\r\n\r\nevent: message\r\ndata: {{\"jsonrpc\":\"2.0\",\"method\":\"notifications/progress\"}}\r\n\r\nevent: message\r\ndata: {rpc}\r\n\r\n"
                        ),
                    )
                } else {
                    ("application/json", rpc.to_string())
                };
                let mut response = Response::from_string(body)
                    .with_status_code(if status == 0 { 200 } else { status })
                    .with_header(
                        Header::from_bytes("Content-Type", format!("{ctype}; charset=utf-8"))
                            .unwrap(),
                    );
                if method == "initialize" {
                    response.add_header(
                        Header::from_bytes("Mcp-Session-Id", format!("session-{session}")).unwrap(),
                    );
                }
                request.respond(response).unwrap();
            }
        });
        Self { endpoint, worker }
    }
    pub fn finish(self) {
        self.worker.join().unwrap();
    }
}
