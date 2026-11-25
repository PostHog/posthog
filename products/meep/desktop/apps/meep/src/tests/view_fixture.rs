use super::*;
use meep_posthog::mcp::{McpClient, McpSession};
use meep_wire::views::{Stage, ViewCommand};

pub(super) fn tracker(topic: TopicId) -> String {
    r#"async function refresh() {
      try { const tasks=await host.call("topics","tasks",{topic:"TOPIC_ID"});
        setState({tasks:tasks || [], loaded:true});
      } catch (e) { setState({error:String(e)}); }
    }
    view({state:{tasks:[],loaded:false,error:""},init:refresh,commands:{refresh},
      inspect:s=>({count:s.tasks.length}),
      render(s) {
        const groups=[["InProgress","In progress"],["NeedsYou","Needs review"],["Todo","Up next"],["Done","Completed"]];
        return Page({align:"center"},Scroll({id:"tracker-scroll"},Reading({gap:20},
          Header({title:"Launch tracker",subtitle:"New web navigation · Rollout work"}),
          s.error ? ErrorMessage(s.error) : !s.loaded ? Loading() :
          groups.map(([key,title])=>{
            const rows=s.tasks.filter(t=>t.column===key);
            return rows.length ? Column({gap:4},Section(title,rows.length+(rows.length===1?" task":" tasks")),
              rows.map(t=>Row({gap:10,py:8,border:"bottom"},Icon(key==="Done"?"circle-check":key==="NeedsYou"?"circle-dot":"circle",{size:14}),Text(t.title,{size:13})))) : null;
          }))));
      }
    });"#.replace("TOPIC_ID",&topic.to_string())
}

pub(super) async fn session(lab: &Lab, id: Uuid) -> Result<McpSession> {
    let expected = format!("https://topics.example.test/tunnel/v1/views/{id}/mcp");
    let body = tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            if let Some(body) = lab
                .upstream
                .view_runs
                .lock()
                .unwrap()
                .iter()
                .rev()
                .find(|(_, body)| body["imported_mcp_servers"][0]["url"] == expected)
                .map(|(_, body)| body.clone())
            {
                return body;
            }
            tokio::time::sleep(std::time::Duration::from_millis(15)).await;
        }
    })
    .await?;
    let config = &body["imported_mcp_servers"][0];
    assert_eq!(config["name"], "meep-view");
    assert_eq!(config["type"], "http");
    let header = &config["headers"][0];
    assert_eq!(header["name"], "Authorization");
    let token = header["value"]
        .as_str()
        .unwrap()
        .strip_prefix("Bearer ")
        .unwrap();
    // Map the test tunnel hostname to our loopback service, just as a reverse proxy does.
    McpClient::new(&format!("{}/v1/views/{id}/mcp", lab.backend.server), None)?
        .initialize(token)
        .await
}
pub(super) async fn tool(mcp: &mut McpSession, name: &str, args: Value) -> Result<Value> {
    let result = mcp.call(name, args).await?;
    let value = result.content[0]["text"]
        .as_str()
        .context("Missing MCP result")?;
    anyhow::ensure!(!result.is_error, "{value}");
    Ok(serde_json::from_str(value).unwrap_or_else(|_| json!(value)))
}
pub(super) async fn publish(mcp: &mut McpSession, topic: TopicId) -> Result<Value> {
    tool(mcp,"write_view",json!({"expected":0,"source":tracker(topic),"title":"Launch tracker","icon":"🚀","color":"orange"})).await
}

#[test]
fn offline_creation_cloud_authoring_validation_restore_and_live_reads() -> Result<()> {
    let lab = Lab::open()?;
    let topic = lab.seed()?;
    let id = Uuid::new_v4();
    let replica = lab._dir.path().join("second-replica.sqlite");
    // No listener at this address. Reopen the same database using the paired server after reconnect.
    let listener = std::net::TcpListener::bind("127.0.0.1:0")?;
    let offline = format!("http://{}", listener.local_addr()?);
    drop(listener);
    let device = std::fs::read_to_string(lab._dir.path().join("device-token"))?;
    let c = Client::open(
        &replica,
        Arc::new(HttpTransport::new(&offline, device.trim())?),
    )?;
    c.issue_view(
        id,
        ViewCommand::Create {
            prompt: "Track launch work across topics".into(),
            options: Default::default(),
        },
    )?;
    assert!(lab.runtime.block_on(c.sync_once()).is_err());
    assert_eq!(c.views()?[0].id, id);
    assert!(lab.upstream.view_runs.lock().unwrap().is_empty());
    drop(c);
    let c = Client::open(
        &replica,
        Arc::new(HttpTransport::new(&lab.backend.server, device.trim())?),
    )?;
    lab.runtime
        .block_on(verify_authoring(&lab, &c, id, topic, device.trim()))
}

async fn verify_authoring(
    lab: &Lab,
    c: &Client,
    id: Uuid,
    topic: TopicId,
    device: &str,
) -> Result<()> {
    c.sync_once().await?;
    c.issue(
        topic,
        Command::AddTask {
            id: TaskId(Uuid::new_v4()),
            title: "Verify the view status".into(),
        },
    )?;
    c.sync_once().await?;
    let mut mcp = session(lab, id).await?;
    assert!(
        mcp.list_tools()
            .await?
            .iter()
            .any(|t| t.name == "patch_view")
    );
    let contract = tool(&mut mcp, "design_system", json!({"topic":"host"})).await?;
    let contract = contract.as_str().context("Missing host contract")?;
    assert!(contract.contains("Use column for filtering and status for display"));
    let first = publish(&mut mcp, topic).await?;
    assert_eq!(first["generation"], 1);
    let invalid = tool(
        &mut mcp,
        "write_view",
        json!({"expected":1,"source":"view({ render() { throw Error('broken layout') } })"}),
    )
    .await
    .unwrap_err();
    assert!(invalid.to_string().contains("broken layout"));
    let populated = format!(
        "view({{state:{{rows:[]}},async init(){{setState({{rows:await host.call('topics','tasks',{{topic:'{topic}'}})}})}},render:s=>Page(s.rows.map(row=>Pressable({{}},Text(row.title))) )}})"
    );
    let invalid = tool(
        &mut mcp,
        "write_view",
        json!({"expected":1,"source":populated}),
    )
    .await
    .unwrap_err();
    assert!(invalid.to_string().contains("Unknown element Pressable"));
    let current = tool(&mut mcp, "read_view", json!({})).await?;
    assert_eq!(current["generation"], 1);
    assert_eq!(current["source"], tracker(topic));
    let args = json!({"source":"topics","tool":"tasks","arguments":{"topic":topic}});
    let actual = tool(&mut mcp, "read_source", args.clone()).await?;
    assert_eq!(
        actual,
        meep_wire::views::topic_rows(&lab.server.engine().topic(topic)?, "tasks")?
    );
    assert!(!actual.as_array().unwrap().is_empty());
    assert!(actual.as_array().unwrap().iter().all(|row| {
        row["column"].is_string() && row["status"].as_str().is_some_and(|s| !s.is_empty())
    }));
    assert_eq!(c.view_source(id, args).await?, actual);
    let secret = lab.server.engine().routine_secret(topic, "review")?;
    let op = meep_engine::RoutineOp::RefreshView {
        view: id,
        data: json!({"week":12,"completed":7}),
    };
    lab.server
        .engine()
        .routine_callback_once(topic, "review", &secret, Uuid::new_v4(), op)
        .await?;
    let dataset = tool(
        &mut mcp,
        "read_source",
        json!({"source":"topics","tool":"routine_data","arguments":{"topic":topic}}),
    )
    .await?;
    assert_eq!(dataset["completed"], 7);
    let external = tool(
        &mut mcp,
        "read_source",
        json!({"source":INSTALLATION,"tool":"list_recent","arguments":{}}),
    )
    .await?;
    assert_eq!(external["data"][0], "First observation");
    let table=tool(&mut mcp,"read_source",json!({"source":"topics","tool":"file","arguments":{"topic":topic,"path":"notes/review.md"}})).await?;
    assert_eq!(table, "Navigation review notes");
    let patch = tool(
        &mut mcp,
        "patch_view",
        json!({"expected":1,"old":"Launch tracker","new":"Launch overview"}),
    )
    .await?;
    assert_eq!(patch["generation"], 2);
    assert!(
        tool(
            &mut mcp,
            "write_view",
            json!({"expected":1,"source":tracker(topic)})
        )
        .await
        .is_err()
    );
    c.sync_once().await?;
    c.issue_view(
        id,
        ViewCommand::Restore {
            expected: 2,
            number: 1,
        },
    )?;
    c.sync_once().await?;
    let restored = c.views()?.remove(0);
    assert_eq!(restored.generation(), 3);
    assert_eq!(restored.revisions[2].source, tracker(topic));
    assert_eq!(lab.upstream.view_runs.lock().unwrap().len(), 1);
    // The device token is deliberately invalid at the authoring endpoint.
    let endpoint = format!("{}/v1/views/{id}/mcp", lab.backend.server);
    assert!(
        McpClient::new(&endpoint, None)?
            .initialize(device)
            .await
            .is_err()
    );
    lab.upstream.finish_views.store(true, Ordering::SeqCst);
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            c.sync_once().await?;
            if matches!(c.views()?[0].turns[0].stage, Stage::Finished(_)) {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }
        Ok::<_, anyhow::Error>(())
    })
    .await??;
    assert!(mcp.list_tools().await.is_err());
    let session_id = restored.turns[0].session;
    c.issue_view(
        id,
        ViewCommand::Ask {
            session: session_id,
            prompt: "Show progress by owner".into(),
            options: Default::default(),
        },
    )?;
    c.sync_once().await?;
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            if lab.upstream.view_runs.lock().unwrap().len() == 2 {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;
    let runs = lab.upstream.view_runs.lock().unwrap();
    assert_eq!(runs[1].1["resume_from_run_id"], json!(runs[0].0));
    Ok(())
}

#[gpui::test]
fn sidebar_create_edit_session_and_remove_without_a_topic(cx: &mut TestAppContext) {
    let mut lab = Lab::open().unwrap();
    lab.disconnect().unwrap();
    let (desktop, ui) = fixture(&lab, cx);
    draw(ui);
    click(ui, "plus");
    click(ui, "new-view");
    ui.simulate_input("Show my week");
    ui.simulate_keystrokes("enter");
    draw(ui);
    let id = ui.update(|_, cx| match desktop.read(cx).page {
        Page::View(id) => id,
        ref p => panic!("Expected a view, got {p:?}"),
    });
    assert!(lab.backend.client.topics().unwrap().is_empty());
    let views = lab.backend.client.views().unwrap();
    assert_eq!(views[0].turns[0].prompt, "Show my week");
    click(ui, "view-settings");
    ui.update(|w, cx| {
        desktop
            .read(cx)
            .name
            .clone()
            .update(cx, |e, cx| e.set_value("My week", w, cx))
    });
    click(ui, "save-view");
    assert_eq!(lab.backend.client.views().unwrap()[0].title, "My week");
    click(ui, "all-view-sessions");
    click(ui, "new-agent-session");
    ui.simulate_input("Include open reviews");
    ui.simulate_keystrokes("enter");
    draw(ui);
    let turns = &lab.backend.client.views().unwrap()[0].turns;
    assert_eq!(turns.len(), 2);
    assert_ne!(turns[0].session, turns[1].session);
    click(ui, "close-agent-panel");
    click(ui, &format!("view-{id}"));
    click(ui, "view-settings");
    click(ui, "delete-view");
    click(ui, "delete-view");
    assert!(lab.backend.client.views().unwrap().is_empty());
}
