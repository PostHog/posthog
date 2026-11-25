//! Loopback implementation of the store contract used by settings and previews.
use super::*;
use axum::extract::{Path, Query};
use meep_wire::mcp_store::{Operation, Outcome, Policy};

#[derive(Default)]
pub(super) struct Fixture {
    installed: Vec<Value>,
    policies: BTreeMap<String, String>,
}

pub(super) fn catalog() -> Vec<Value> {
    [
        ("Linear", "linear.app", "Issues, cycles and projects", "dev"),
        (
            "GitHub",
            "github.com",
            "Repositories and pull requests",
            "dev",
        ),
        ("Notion", "notion.so", "Pages and databases", "productivity"),
        (
            "Slack",
            "slack.com",
            "Channels and conversations",
            "communication",
        ),
        (
            "Figma",
            "figma.com",
            "Design files and components",
            "design",
        ),
        (
            "Sentry",
            "sentry.io",
            "Errors and performance issues",
            "dev",
        ),
        (
            "Atlassian",
            "atlassian.com",
            "Jira issues and Confluence pages",
            "productivity",
        ),
        (
            "Stripe",
            "stripe.com",
            "Payments, customers and invoices",
            "business",
        ),
        (
            "HubSpot",
            "hubspot.com",
            "Contacts, deals and companies",
            "business",
        ),
        (
            "Intercom",
            "intercom.com",
            "Conversations and help center articles",
            "communication",
        ),
        ("Asana", "asana.com", "Tasks and projects", "productivity"),
        ("Vercel", "vercel.com", "Deployments and logs", "dev"),
    ]
    .into_iter()
    .enumerate()
    .map(|(i, (name, host, description, category))| {
        json!({
            "id":Uuid::from_u128(i as u128+1),"name":name,
            "url":format!("https://mcp.{host}/mcp"),"description":description,
            "auth_type":if name=="Sentry" {"api_key"}else{"oauth"},
            "category":category,"icon_domain":host
        })
    })
    .collect()
}
#[cfg(feature = "ui-previews")]
pub(super) fn installations() -> Vec<Value> {
    catalog().into_iter().take(3).enumerate().map(|(i,t)| {
        json!({
            "id":Uuid::from_u128(i as u128+101),"template_id":t["id"],
            "name":t["name"],"url":t["url"],"auth_type":"oauth","is_owner":true,
            "is_enabled":true,"needs_reauth":i==1,"pending_oauth":false,"tool_count":([3,8,0][i])
        })
    }).collect()
}
pub(super) fn tools_fixture() -> Vec<Value> {
    [
        (
            "list_issues",
            "Search and filter issues in your workspace.",
            "approved",
        ),
        (
            "create_issue",
            "Create an issue in a team.",
            "needs_approval",
        ),
        ("delete_issue", "Permanently delete an issue.", "do_not_use"),
    ]
    .map(|(name, description, policy)| {
        json!({
            "tool_name":name,"description":description,"approval_state":policy,
            "locked":false,"team_state":"approved"
        })
    })
    .to_vec()
}
pub(super) fn routes() -> Router<Arc<Upstream>> {
    async fn install(State(s): State<Arc<Upstream>>, Json(body): Json<Value>) -> Json<Value> {
        assert_eq!(body["scope"], "personal");
        assert_eq!(body["install_source"], "posthog-code");
        let mut rows = s.store.lock().unwrap();
        let id = Uuid::new_v4();
        let mut row = if let Some(template) = body.get("template_id") {
            if *template == Uuid::from_u128(1).to_string() {
                return Json(
                    json!({"redirect_url":"https://login.example.test/authorize?state=fixture"}),
                );
            }
            assert_eq!(body["api_key"], "fixture-key");
            catalog()
                .into_iter()
                .find(|t| t["id"] == *template)
                .unwrap()
        } else {
            assert_eq!(body["auth_type"], "api_key");
            assert_eq!(body["api_key"], "fixture-key");
            body.clone()
        };
        let template = body.get("template_id").cloned();
        row = json!({"id":id,"name":row["name"],"url":row["url"],"auth_type":row["auth_type"],"template_id":template,"is_owner":true,"is_enabled":true,"needs_reauth":false,"pending_oauth":false,"tool_count":3});
        rows.installed.push(row.clone());
        Json(row)
    }
    async fn tools(State(s): State<Arc<Upstream>>, Path(_): Path<Uuid>) -> Json<Value> {
        let state = s.store.lock().unwrap();
        let mut tools = tools_fixture();
        for t in &mut tools {
            if let Some(policy) = state.policies.get(t["tool_name"].as_str().unwrap()) {
                t["approval_state"] = json!(policy);
            }
        }
        Json(json!({"results":tools}))
    }
    Router::new()
        .route(
            "/api/projects/7/mcp_servers/",
            get(
                |h: axum::http::HeaderMap, Query(q): Query<BTreeMap<String, String>>| async move {
                    assert_eq!(h["authorization"], "Bearer test-session");
                    // Pages of four, as PostHog pages its store, so Browse must follow `next`.
                    let all = catalog();
                    let from: usize = q.get("offset").map_or(0, |o| o.parse().unwrap());
                    let to = (from + 4).min(all.len());
                    let next = (to < all.len()).then(|| format!("?limit=4&offset={to}"));
                    Json(json!({"count":all.len(),"next":next,"results":all[from..to]}))
                },
            ),
        )
        .route(
            "/api/projects/7/mcp_server_installations/",
            get(|State(s): State<Arc<Upstream>>| async move {
                Json(json!({"results":s.store.lock().unwrap().installed}))
            }),
        )
        .route(
            "/api/projects/7/mcp_server_installations/install_custom/",
            post(install),
        )
        .route(
            "/api/projects/7/mcp_server_installations/install_template/",
            post(install),
        )
        .route(
            "/api/projects/7/mcp_server_installations/authorize/",
            get(|Query(q): Query<BTreeMap<String, String>>| async move {
                assert!(Uuid::parse_str(&q["installation_id"]).is_ok());
                assert_eq!(q["install_source"], "posthog-code");
                Json(json!({"redirect_url":"https://login.example.test/authorize?state=fixture"}))
            }),
        )
        .route(
            "/api/projects/7/mcp_server_installations/{id}/tools/",
            get(tools),
        )
        .route(
            "/api/projects/7/mcp_server_installations/{id}/tools/refresh/",
            post(tools),
        )
        .route(
            "/api/projects/7/mcp_server_installations/{id}/tools/{name}/",
            axum::routing::patch(
                |Path((_id, name)): Path<(Uuid, String)>,
                 State(s): State<Arc<Upstream>>,
                 Json(body): Json<Value>| async move {
                    s.store
                        .lock()
                        .unwrap()
                        .policies
                        .insert(name, body["approval_state"].as_str().unwrap().into());
                    Json(body)
                },
            ),
        )
        .route(
            "/api/projects/7/mcp_server_installations/{id}/",
            axum::routing::delete(
                |State(s): State<Arc<Upstream>>, Path(id): Path<Uuid>| async move {
                    s.store
                        .lock()
                        .unwrap()
                        .installed
                        .retain(|r| r["id"] != id.to_string());
                    StatusCode::NO_CONTENT
                },
            ),
        )
}

fn request(lab: &Lab, operation: Operation) -> Result<Outcome> {
    lab.runtime
        .block_on(lab.backend.client.mcp_store(&operation))
}
fn installed(lab: &Lab) -> Result<Vec<meep_wire::mcp_store::Installed>> {
    match request(lab, Operation::Browse)? {
        Outcome::Catalog(servers, templates) => {
            // Every page of the store, not only the first.
            assert_eq!(templates.len(), catalog().len());
            Ok(servers)
        }
        _ => anyhow::bail!("expected the server catalog"),
    }
}
#[test]
fn install_custom_server_with_api_key() -> Result<()> {
    let lab = Lab::open()?;
    request(
        &lab,
        Operation::Custom {
            name: "Research".into(),
            url: "https://example.test/mcp".into(),
            oauth: false,
            api_key: Some("fixture-key".into()),
        },
    )?;
    assert_eq!(installed(&lab)?[0].name, "Research");
    Ok(())
}
#[test]
fn oauth_install_and_reconnect_hand_off_browser_url() -> Result<()> {
    let lab = Lab::open()?;
    for operation in [
        Operation::Template {
            id: Uuid::from_u128(1),
            api_key: None,
        },
        Operation::Authorize {
            id: Uuid::from_u128(101),
        },
    ] {
        let Outcome::Browser(url) = request(&lab, operation)? else {
            anyhow::bail!("expected a browser handoff")
        };
        assert_eq!(url, "https://login.example.test/authorize?state=fixture");
    }
    Ok(())
}
#[test]
fn clearing_cache_preserves_preferences_and_refuses_pending_edits() -> Result<()> {
    let lab = Lab::open()?;
    let client = &lab.backend.client;
    let id = lab.seed()?;
    lab.runtime.block_on(client.sync_once())?;
    lab.runtime.block_on(client.clear_replica_cache())?;
    assert!(client.topic(id)?.is_none());
    assert_eq!(client.preference::<bool>("signed-in")?, Some(true));
    lab.runtime.block_on(client.sync_once())?;
    assert!(client.topic(id)?.is_some());
    client.issue(
        id,
        Command::SetMission {
            mission: "A pending edit".into(),
        },
    )?;
    assert!(lab.runtime.block_on(client.clear_replica_cache()).is_err());
    assert_eq!(client.topic(id)?.unwrap().topic.mission, "A pending edit");
    Ok(())
}

#[gpui::test]
fn server_detail_applies_policy_and_confirms_removal(cx: &mut TestAppContext) {
    let lab = Lab::open().unwrap();
    request(
        &lab,
        Operation::Template {
            id: Uuid::from_u128(6),
            api_key: Some("fixture-key".into()),
        },
    )
    .unwrap();
    let server = installed(&lab).unwrap().pop().unwrap();
    assert_eq!(server.template_id, Some(Uuid::from_u128(6)));
    let id = server.id;
    let (view, ui) = fixture(&lab, cx);
    let wait = |ui: &mut VisualTestContext, predicate: fn(&Desktop) -> bool| {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        while !ui.update(|_, cx| predicate(view.read(cx))) {
            assert!(
                std::time::Instant::now() < deadline,
                "settings request timed out"
            );
            draw(ui);
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
    };
    click(ui, "settings");
    click(ui, "settings-mcp servers");
    wait(ui, |s| !s.mcp.servers.is_empty());
    click(ui, &format!("server-{id}"));
    wait(ui, |s| !s.mcp.tools.is_empty());
    click(ui, "list_issues-2");
    wait(ui, |s| s.mcp.tools[0].approval_state == Policy::DoNotUse);
    let Outcome::Tools(refreshed) = request(&lab, Operation::Tools { id, refresh: true }).unwrap()
    else {
        panic!("expected refreshed tools");
    };
    assert!(refreshed[0].approval_state == Policy::DoNotUse);
    click(ui, "remove-server");
    click(ui, "cancel-remove");
    assert_eq!(installed(&lab).unwrap().len(), 1);
    click(ui, "remove-server");
    click(ui, "confirm-remove");
    wait(ui, |s| s.mcp.servers.is_empty());
    assert!(installed(&lab).unwrap().is_empty());
}
