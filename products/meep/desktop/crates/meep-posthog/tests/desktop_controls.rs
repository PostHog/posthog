use anyhow::Result;
use meep_posthog::tasks::{NewTurn, Tasks};
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    io::{BufRead, BufReader, Read, Write},
    net::{TcpListener, TcpStream},
};
use uuid::Uuid;

struct Request {
    path: String,
    headers: HashMap<String, String>,
    body: Vec<u8>,
}
fn read(stream: &TcpStream) -> Request {
    let mut input = BufReader::new(stream);
    let mut line = String::new();
    input.read_line(&mut line).unwrap();
    let path = line.split_whitespace().nth(1).unwrap().to_owned();
    let mut headers = HashMap::new();
    loop {
        line.clear();
        input.read_line(&mut line).unwrap();
        if line == "\r\n" {
            break;
        }
        let (key, value) = line.trim_end().split_once(':').unwrap();
        headers.insert(key.to_lowercase(), value.trim().to_owned());
    }
    let mut body = vec![0; headers["content-length"].parse::<usize>().unwrap()];
    input.read_exact(&mut body).unwrap();
    Request {
        path,
        headers,
        body,
    }
}
fn reply(mut s: TcpStream, v: Value) {
    let text = v.to_string();
    write!(s,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{text}",text.len()).unwrap();
}

#[tokio::test]
async fn stages_files_before_runs_and_scopes_live_attachments_to_the_run() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let origin = format!("http://{}", listener.local_addr()?);
    let api = Tasks::new(&origin, 7)?;
    let task = Uuid::from_u128(7);
    let run = Uuid::from_u128(11);
    let worker = std::thread::spawn(move || {
        for live in [false, true] {
            let root = format!(
                "/api/projects/7/tasks/{task}/{}",
                if live {
                    format!("runs/{run}/artifacts")
                } else {
                    "staged_artifacts".to_owned()
                }
            );
            let (s, _) = listener.accept().unwrap();
            let req = read(&s);
            assert_eq!(req.path, format!("{root}/prepare_upload/"));
            assert_eq!(req.headers["authorization"], "Bearer fixture");
            let input: Value = serde_json::from_slice(&req.body).unwrap();
            let mut item = input["artifacts"][0].clone();
            assert_eq!(item["name"], "notes.txt");
            assert_eq!(item["size"], 8);
            assert_eq!(item["type"], "user_attachment");
            item["id"] = json!("file-1");
            item["storage_path"] = json!("reserved/notes.txt");
            item["presigned_post"] = json!({"url":format!("{origin}/object-store"),"fields":{"key":"reserved/notes.txt","policy":"fixture-policy"}});
            reply(s, json!({"artifacts":[item]}));
            let (s, _) = listener.accept().unwrap();
            let req = read(&s);
            assert_eq!(req.path, "/object-store");
            assert!(!req.headers.contains_key("authorization"));
            let multipart = String::from_utf8(req.body).unwrap();
            assert!(
                multipart.contains("filename=\"notes.txt\"")
                    && multipart.contains("contents")
                    && multipart.contains("fixture-policy")
            );
            reply(s, Value::Null);
            let (s, _) = listener.accept().unwrap();
            let req = read(&s);
            assert_eq!(req.path, format!("{root}/finalize_upload/"));
            let final_req: Value = serde_json::from_slice(&req.body).unwrap();
            assert!(final_req["artifacts"][0].get("presigned_post").is_none());
            assert_eq!(
                final_req["artifacts"][0]["storage_path"],
                "reserved/notes.txt"
            );
            reply(s, json!({"artifacts":[{"id":"file-1"}]}));
            let (s, _) = listener.accept().unwrap();
            let req = read(&s);
            let cmd: Value = serde_json::from_slice(&req.body).unwrap();
            if live {
                assert_eq!(
                    req.path,
                    format!("/api/projects/7/tasks/{task}/runs/{run}/command/")
                );
                assert_eq!(cmd["method"], "user_message");
                assert_eq!(
                    cmd["params"],
                    json!({"content":"now","artifact_ids":["file-1"],"steer":true})
                );
                reply(
                    s,
                    json!({"jsonrpc":"2.0","result":{"queued":true},"id":cmd["id"]}),
                );
            } else {
                assert_eq!(req.path, format!("/api/projects/7/tasks/{task}/run/"));
                assert_eq!(
                    cmd,
                    json!({"mode":"interactive","model":"test-model","reasoning_effort":"high","pending_user_artifact_ids":["file-1"]})
                );
                reply(s, json!({"run":{"id":run,"status":"queued"}}));
            }
        }
    });
    let dir = tempfile::tempdir()?;
    let path = dir.path().join("notes.txt");
    std::fs::write(&path, b"contents")?;
    let file = api.upload_attachment("fixture", task, None, &path).await?;
    api.start_turn_with_effort(
        "fixture",
        task,
        NewTurn {
            model: Some("test-model"),
            artifacts: &[file],
            ..Default::default()
        },
        Some("high"),
    )
    .await?;
    let file = api
        .upload_attachment("fixture", task, Some(run), &path)
        .await?;
    api.command(
        "fixture",
        task,
        run,
        Uuid::new_v4(),
        "user_message",
        json!({"content":"now","artifact_ids":[file],"steer":true}),
    )
    .await?;
    worker.join().unwrap();
    Ok(())
}

#[tokio::test]
async fn run_controls_use_their_own_json_rpc_receipts() -> Result<()> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let api = Tasks::new(&format!("http://{}", listener.local_addr()?), 7)?;
    let cases = [
        ("set_config_option", json!({"configOptions":[]})),
        ("permission_response", json!({"resolved":true})),
        ("cancel", json!({"cancelled":true})),
        ("user_message", json!({"queued":false})),
    ];
    let replies = cases.clone();
    let worker = std::thread::spawn(move || {
        for (method, result) in replies {
            let (socket, _) = listener.accept().unwrap();
            let req: Value = serde_json::from_slice(&read(&socket).body).unwrap();
            assert_eq!(req["method"], method);
            reply(
                socket,
                json!({"jsonrpc":"2.0","id":req["id"],"result":result}),
            );
        }
    });
    for (method, expected) in cases {
        let actual = api
            .command(
                "fixture",
                Uuid::nil(),
                Uuid::nil(),
                Uuid::new_v4(),
                method,
                json!({}),
            )
            .await;
        if method == "user_message" {
            assert!(actual.is_err());
        } else {
            assert_eq!(actual?, expected);
        }
    }
    worker.join().unwrap();
    Ok(())
}

#[tokio::test]
async fn log_pages_use_absolute_cursors_and_separate_the_state_preamble() -> Result<()> {
    use meep_posthog::tasks::LogWindow;
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let api = Tasks::new(&format!("http://{}", listener.local_addr()?), 7)?;
    let worker = std::thread::spawn(move || {
        for (suffix, offset, count, preamble, body) in [
            ("", 7, 9, 1, "{\"state\":true}\n{\"i\":7}\n{\"i\":8}\n"),
            ("&before=7", 5, 10, 0, "{\"i\":5}\n{\"i\":6}"),
            ("&start=9", 9, 10, 0, "{\"i\":9}\n"),
        ] {
            let (mut stream, _) = listener.accept().unwrap();
            let mut input = BufReader::new(&stream);
            let mut request = String::new();
            input.read_line(&mut request).unwrap();
            assert!(request.contains(&format!("/logs/?view=thread&tail_bytes=65536{suffix} HTTP")));
            loop {
                request.clear();
                input.read_line(&mut request).unwrap();
                if request == "\r\n" {
                    break;
                }
            }
            write!(stream,"HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\nX-Log-Origin: chain\r\nX-Log-Offset: {offset}\r\nX-Log-Count: {count}\r\nX-Log-Preamble: {preamble}\r\n\r\n",body.len()).unwrap();
            for byte in body.as_bytes().chunks(3) {
                stream.write_all(byte).unwrap();
            }
        }
    });
    for (window, offset, expected) in [
        (LogWindow::Latest, 7, vec![7, 8]),
        (LogWindow::Before(7), 5, vec![5, 6]),
        (LogWindow::From(9), 9, vec![9]),
    ] {
        let page = api
            .conversation_page("fixture", Uuid::nil(), Uuid::nil(), window)
            .await?;
        assert_eq!(page.offset, offset);
        assert_eq!(page.preamble.len(), usize::from(offset == 7));
        assert_eq!(
            page.entries
                .iter()
                .map(|v| v["i"].as_u64().unwrap())
                .collect::<Vec<_>>(),
            expected
        );
    }
    worker.join().unwrap();
    Ok(())
}
