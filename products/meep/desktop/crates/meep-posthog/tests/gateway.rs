use anyhow::Result;
use meep_posthog::api::{ApiError, ProjectEndpoint};
use meep_posthog::mcp::Gateway;
use serde_json::{Value, json};
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::TcpListener,
};
use uuid::Uuid;

#[tokio::test]
async fn discovers_tools_and_preserves_server_approval_decisions() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let origin = format!("http://{}", listener.local_addr()?);
    let id = Uuid::from_u128(1);
    let worker = std::thread::spawn(move || {
        for n in 0..3 {
            let (mut socket, _) = listener.accept().unwrap();
            let mut buf = BufReader::new(socket.try_clone().unwrap());
            let mut header = String::new();
            loop {
                let mut line = String::new();
                buf.read_line(&mut line).unwrap();
                if line == "\r\n" {
                    break;
                }
                header.push_str(&line);
            }
            assert!(
                header
                    .to_lowercase()
                    .contains("authorization: bearer fixture")
            );
            let root = "/api/projects/@current/mcp_server_installations/";
            let (status, response) = if n == 0 {
                assert!(header.starts_with(&format!("GET {root}available_tools/ ")));
                (
                    "200 OK",
                    json!({"servers":[{"installation_id":id,"name":"Docs","slug":"docs","tools":[{"name":"lookup","description":"Read","annotations":{},"input_schema":{"type":"object"},"approval_state":"approved"}]}]}),
                )
            } else {
                assert!(header.starts_with(&format!("POST {root}{id}/call_tool/ ")));
                let length: usize = header
                    .to_lowercase()
                    .lines()
                    .find_map(|s| {
                        s.strip_prefix("content-length: ")
                            .map(|v| v.trim().parse().unwrap())
                    })
                    .unwrap();
                let mut body = vec![0; length];
                buf.read_exact(&mut body).unwrap();
                assert_eq!(
                    serde_json::from_slice::<Value>(&body).unwrap(),
                    json!({"tool_name":"lookup","arguments":{"q":"test"}})
                );
                if n == 1 {
                    (
                        "200 OK",
                        json!({"is_error":false,"content":[{"type":"text","text":"found"}]}),
                    )
                } else {
                    (
                        "403 Forbidden",
                        json!({"reason":"needs_approval","detail":"Approval required"}),
                    )
                }
            };
            let data = response.to_string();
            write!(socket,"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{data}",data.len()).unwrap();
        }
    });
    let gateway = Gateway::current(&origin)?;
    let servers = gateway.available("fixture").await?;
    assert_eq!(servers[0].tools[0].approval_state, "approved");
    let args = json!({"q":"test"});
    assert!(
        !gateway
            .call("fixture", id, "lookup", args.as_object().unwrap())
            .await?
            .is_error
    );
    let err = gateway
        .call("fixture", id, "lookup", args.as_object().unwrap())
        .await
        .unwrap_err();
    assert_eq!(
        err.downcast_ref::<ApiError>().unwrap().code,
        "needs_approval"
    );
    worker.join().unwrap();
    Ok(())
}

#[tokio::test]
async fn project_transport_refuses_unscoped_origins_and_paths() -> Result<()> {
    for url in [
        "http://example.org",
        "https://user@example.org",
        "https://example.org/sub/",
    ] {
        assert!(ProjectEndpoint::new(url, 1, "tasks").is_err());
    }
    let api = ProjectEndpoint::new("https://example.org", 1, "tasks")?;
    for path in [
        "../other/",
        "//another.example/api/",
        "/api/projects/2/tasks/",
    ] {
        assert!(
            api.get::<Value>("unused", path)
                .await
                .unwrap_err()
                .to_string()
                .contains("outside")
        );
    }
    Ok(())
}
