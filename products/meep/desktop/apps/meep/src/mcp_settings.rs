use super::*;
use meep_shell::settings::{
    Tone, danger, empty, field, footer, group, header, item, logo_tile, section,
    status as status_mark, suggestion_with,
};
use meep_ui::gpui_kit::component::{Disableable, Icon};
use meep_wire::mcp_store::{Installed, Operation, Outcome, Policy, Template, ToolPolicy};

#[derive(Default, PartialEq, Eq)]
pub(super) enum Screen {
    #[default]
    List,
    Detail(Uuid),
    Custom,
    TemplateKey(Uuid),
}

pub(super) struct McpSettings {
    pub servers: Vec<Installed>,
    pub catalog: Vec<Template>,
    pub tools: Vec<ToolPolicy>,
    pub screen: Screen,
    pub confirm: bool,
    busy: bool,
    loaded: bool,
    pub message: Option<String>,
    pub failures: BTreeMap<Uuid, String>,
    name: Entity<InputState>,
    url: Entity<InputState>,
    key: Entity<InputState>,
    pub oauth: bool,
    /// Filters the store by name and description as the person types.
    pub search: Entity<InputState>,
    /// Store category shown, or every category.
    pub category: Option<String>,
}

impl McpSettings {
    pub fn new(w: &mut Window, cx: &mut Context<Desktop>) -> Self {
        Self {
            servers: vec![],
            catalog: vec![],
            tools: vec![],
            screen: Screen::List,
            confirm: false,
            busy: false,
            loaded: false,
            message: None,
            failures: BTreeMap::new(),
            name: cx.new(|cx| InputState::new(w, cx).placeholder("Server name")),
            url: cx.new(|cx| InputState::new(w, cx).placeholder("https://…")),
            key: key_field(w, cx),
            oauth: true,
            search: {
                let search = cx.new(|cx| InputState::new(w, cx).placeholder("Search MCP servers…"));
                cx.subscribe(&search, |_, _, _: &InputEvent, cx| cx.notify())
                    .detach();
                search
            },
            category: None,
        }
    }
}

/// A store category as a label: "dev" reads "Developer tools".
fn category_name(key: &str) -> String {
    match key {
        "dev" | "developer" | "developer_tools" => "Developer tools".into(),
        "business" => "Business".into(),
        "productivity" => "Productivity".into(),
        "communication" => "Communication".into(),
        "design" => "Design".into(),
        "data" => "Data".into(),
        "" | "other" => "Other".into(),
        other => {
            let words = other.replace(['_', '-'], " ");
            let mut chars = words.chars();
            chars
                .next()
                .map(|c| c.to_uppercase().chain(chars).collect())
                .unwrap_or_default()
        }
    }
}

/// Every word of the query appears in the name or the description.
fn matches_query(t: &Template, query: &str) -> bool {
    let hay = format!(
        "{} {} {}",
        t.name,
        t.description,
        t.category.as_deref().unwrap_or("")
    )
    .to_lowercase();
    query
        .to_lowercase()
        .split_whitespace()
        .all(|word| hay.contains(word))
}

pub(super) fn policy_name(policy: Policy) -> &'static str {
    match policy {
        Policy::Approved => "Allowed",
        Policy::NeedsApproval => "Ask first",
        Policy::DoNotUse => "Off",
    }
}

pub(super) fn policy_picker(
    id: &str,
    current: Policy,
    ceiling: Option<Policy>,
    locked: bool,
    cx: &Context<Desktop>,
    select: impl Fn(&mut Desktop, Policy, &mut Window, &mut Context<Desktop>) + 'static,
) -> Div {
    if locked {
        return meep_shell::settings::value_text(policy_name(current));
    }
    let choices: Vec<_> = [Policy::Approved, Policy::NeedsApproval, Policy::DoNotUse]
        .into_iter()
        .filter(|p| ceiling.is_none_or(|limit| *p >= limit))
        .collect();
    let labels: Vec<_> = choices.iter().map(|p| policy_name(*p)).collect();
    let view = cx.entity().downgrade();
    meep_shell::settings::segmented(
        id,
        &labels,
        choices.iter().position(|p| *p == current),
        move |index, w, cx| {
            let policy = choices[index];
            if policy != current {
                let _ = view.update(cx, |s, cx| {
                    select(s, policy, w, cx);
                    cx.notify()
                });
            }
        },
    )
}

fn key_field(w: &mut Window, cx: &mut App) -> Entity<InputState> {
    cx.new(|cx| {
        InputState::new(w, cx)
            .masked(true)
            .placeholder("Paste API key")
    })
}

/// A tool's identifier as a label: "list_issues" reads "List issues".
fn tool_title(name: &str) -> String {
    let words = name
        .split(['_', '-', ' '])
        .filter(|w| !w.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    let mut chars = words.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().chain(chars).collect(),
        None => name.to_owned(),
    }
}

/// Why a refresh failed, in words for the person reading settings. The raw
/// reason isn't parsed: it stays in the server log for whoever debugs it.
fn failure_words(_reason: &str) -> String {
    "Couldn’t list this server’s tools. Reconnect it or refresh to try again.".into()
}

fn host(url: &str) -> String {
    reqwest::Url::parse(url)
        .ok()
        .and_then(|u| u.host_str().map(str::to_owned))
        .unwrap_or_else(|| "Unknown host".into())
}

impl Desktop {
    pub(super) fn mcp_request(&mut self, op: Operation, w: &Window, cx: &mut Context<Self>) {
        if self.mcp.busy || self.identity.is_none() {
            return;
        }
        self.mcp.busy = true;
        self.mcp.message = None;
        let identity = self.identity.clone();
        let client = self.client().clone();
        let refreshing = matches!(&op, Operation::Tools { refresh: true, .. });
        let tools_id = match &op {
            Operation::SetPolicy { id, .. } | Operation::Tools { id, .. } => Some(*id),
            _ => None,
        };
        self.job(
            async move { client.mcp_store(&op).await },
            w,
            cx,
            move |s, res, w, cx| {
                s.mcp.busy = false;
                if s.identity != identity {
                    return;
                }
                match res {
                    Ok(Outcome::Catalog(servers, catalog)) => {
                        s.mcp.servers = servers;
                        s.mcp.catalog = catalog;
                        s.mcp.loaded = true;
                    }
                    Ok(Outcome::Tools(tools)) => {
                        if tools_id.is_some_and(|id| s.mcp.screen == Screen::Detail(id)) {
                            if let Some(id) = tools_id {
                                if refreshing {
                                    s.mcp.failures.remove(&id);
                                }
                                if let Some(server) =
                                    s.mcp.servers.iter_mut().find(|row| row.id == id)
                                {
                                    server.tool_count = tools.len();
                                }
                            }
                            s.mcp.tools = tools;
                        }
                    }
                    Ok(Outcome::Updated) if tools_id.is_some() => {
                        if let Some(id) = tools_id
                            && s.mcp.screen == Screen::Detail(id)
                        {
                            s.mcp_request(Operation::Tools { id, refresh: false }, w, cx)
                        }
                    }
                    Ok(Outcome::Updated) => {
                        s.mcp.screen = Screen::List;
                        s.mcp.confirm = false;
                        s.mcp_request(Operation::Browse, w, cx);
                    }
                    Ok(Outcome::Browser(url)) => {
                        s.mcp.screen = Screen::List;
                        s.mcp.message = Some(if open::that_detached(url).is_ok() {
                            "Finish signing in in your browser, then return to Topics.".into()
                        } else {
                            "Could not open the browser. Try connecting again.".into()
                        });
                    }
                    Err(e) => {
                        if refreshing && let Some(id) = tools_id {
                            s.mcp.failures.insert(id, e.to_string());
                        }
                        s.mcp.message = Some(e.to_string());
                    }
                }
            },
        );
    }

    pub(super) fn mcp_page(&self, cx: &Context<Self>) -> Div {
        let m = &self.mcp;
        // The same crumbs as a topic's pages: "MCP servers › Linear".
        let back = |current: SharedString| {
            crumbs(
                "back-servers",
                "MCP servers",
                current,
                |s, w, cx| {
                    if s.mcp.busy {
                        return;
                    }
                    s.mcp.screen = Screen::List;
                    s.mcp.confirm = false;
                    s.mcp.key = key_field(w, cx);
                    s.mcp_request(Operation::Browse, w, cx)
                },
                cx,
            )
            .pb(px(16.))
        };
        let page = ui::column().gap_0();
        if self.identity.is_none() {
            return page
                .child(header(
                    "MCP servers",
                    "Connect services through your PostHog account.",
                    None,
                ))
                .child(empty(
                    "Signed out",
                    "Sign in under General to manage your servers.",
                ));
        }
        let notice = |p: Div| {
            p.when_some(m.message.clone(), |p, msg| {
                p.child(ui::caption(msg).pb(px(12.)))
            })
        };
        match m.screen {
            Screen::Custom | Screen::TemplateKey(_) => {
                let template = match m.screen {
                    Screen::TemplateKey(id) => m.catalog.iter().find(|t| t.id == id),
                    _ => None,
                };
                let mut rows = vec![];
                if template.is_none() {
                    rows.push(
                        field(
                            "Name",
                            "",
                            Input::new(&m.name).aria_label("Server name").w_full(),
                        )
                        .into_any_element(),
                    );
                    rows.push(
                        field(
                            "URL",
                            "",
                            Input::new(&m.url).aria_label("Server URL").w_full(),
                        )
                        .into_any_element(),
                    );
                    rows.push(
                        item(
                            "Authentication",
                            "",
                            ui::row().gap(px(4.)).children(
                                [(true, "OAuth"), (false, "API key")].map(|(value, label)| {
                                    control(label, label, m.oauth == value, cx, move |s, _, _| {
                                        s.mcp.oauth = value
                                    })
                                }),
                            ),
                        )
                        .into_any_element(),
                    );
                }
                if template.is_some() || !m.oauth {
                    rows.push(
                        field(
                            "API key",
                            if template.is_some() {
                                "Required by this server."
                            } else {
                                "Leave empty for a public server."
                            },
                            Input::new(&m.key).aria_label("API key").w_full(),
                        )
                        .into_any_element(),
                    );
                }
                let (title, subtitle, install) = match template {
                    Some(t) => (
                        format!("Connect {}", t.name),
                        format!("Paste a {} API key to connect.", t.name),
                        "Connect",
                    ),
                    None => (
                        "Custom server".into(),
                        "Install a server for your PostHog account.".into(),
                        "Install server",
                    ),
                };
                // The form's action closes its card, under the fields it submits.
                rows.push(
                    footer(
                        control("install-custom", install, true, cx, |s, w, cx| {
                            let key = s.mcp.key.read(cx).value().to_string();
                            let api_key = (!key.is_empty()).then_some(key);
                            let op = match s.mcp.screen {
                                Screen::TemplateKey(id) if api_key.is_some() => {
                                    Operation::Template { id, api_key }
                                }
                                Screen::Custom => {
                                    let name = s.mcp.name.read(cx).value().trim().to_owned();
                                    let url = s.mcp.url.read(cx).value().trim().to_owned();
                                    if name.is_empty() || reqwest::Url::parse(&url).is_err() {
                                        s.mcp.message =
                                            Some("Enter a name and a valid server URL.".into());
                                        return;
                                    }
                                    Operation::Custom {
                                        name,
                                        url,
                                        oauth: s.mcp.oauth,
                                        api_key: if s.mcp.oauth { None } else { api_key },
                                    }
                                }
                                _ => {
                                    s.mcp.message = Some("Enter the server’s API key.".into());
                                    return;
                                }
                            };
                            s.mcp.key = key_field(w, cx);
                            s.mcp_request(op, w, cx);
                        })
                        .disabled(m.busy),
                    )
                    .into_any_element(),
                );
                notice(
                    page.child(back(title.clone().into()))
                        .child(header(title, subtitle, None)),
                )
                .child(group(rows))
            }
            Screen::Detail(id) => {
                let Some(server) = m.servers.iter().find(|s| s.id == id) else {
                    return page.child(back("Server unavailable".into())).child(header(
                        "Server unavailable",
                        "Refresh your installations.",
                        None,
                    ));
                };
                let mut p = notice(page.child(back(server.name.clone().into())).child(header(
                    server.name.clone(),
                    host(&server.url),
                    None,
                )));
                let mut actions = ui::row().gap(px(6.));
                if server.is_owner && server.auth_type == "oauth" {
                    actions = actions.child(
                        control(
                            "authorize",
                            if server.pending_oauth || server.needs_reauth {
                                "Connect"
                            } else {
                                "Reconnect"
                            },
                            false,
                            cx,
                            move |s, w, cx| s.mcp_request(Operation::Authorize { id }, w, cx),
                        )
                        .disabled(m.busy),
                    );
                }
                if server.is_owner
                    && server.auth_type == "api_key"
                    && let Some(template) = server.template_id
                    && m.catalog.iter().any(|t| t.id == template)
                {
                    actions = actions.child(
                        control("replace-key", "Reconnect", false, cx, move |s, w, cx| {
                            s.mcp.screen = Screen::TemplateKey(template);
                            s.mcp.key = key_field(w, cx);
                        })
                        .disabled(m.busy),
                    );
                }
                if server.is_owner {
                    actions = actions.child(
                        control("remove-server", "Remove", false, cx, |s, _, _| {
                            s.mcp.confirm = true
                        })
                        .disabled(m.busy),
                    );
                }
                let (label, tone) = state(server, m.failures.contains_key(&id));
                let mut rows = vec![
                    item(
                        "Status",
                        m.failures.get(&id).map_or_else(
                            || format!("{} tools", server.tool_count),
                            |reason| failure_words(reason),
                        ),
                        ui::row()
                            .gap(px(12.))
                            .child(status_mark(label, tone))
                            // The confirmation below holds the only actions while it shows.
                            .when(!m.confirm, |r| r.child(actions)),
                    )
                    .into_any_element(),
                ];
                if m.confirm {
                    rows.push(
                        item(
                            format!("Remove {}?", server.name),
                            "Meep will lose access to its tools.",
                            ui::row()
                                .gap(px(6.))
                                .child(control("cancel-remove", "Cancel", false, cx, |s, _, _| {
                                    s.mcp.confirm = false
                                }))
                                .child(
                                    danger(
                                        control(
                                            "confirm-remove",
                                            "Remove",
                                            true,
                                            cx,
                                            move |s, w, cx| {
                                                s.mcp_request(Operation::Remove { id }, w, cx)
                                            },
                                        ),
                                        cx,
                                    )
                                    .disabled(m.busy),
                                ),
                        )
                        .into_any_element(),
                    );
                }
                p = p.child(group(rows));
                let refresh = control(
                    "refresh-tools",
                    "Refresh tools",
                    false,
                    cx,
                    move |s, w, cx| s.mcp_request(Operation::Tools { id, refresh: true }, w, cx),
                )
                .disabled(m.busy);
                p = p.child(section(
                    "Tools",
                    "Choose when each tool can run.",
                    server.is_owner.then(|| refresh.into_any_element()),
                    false,
                ));
                if m.tools.is_empty() {
                    return p.child(empty(
                        if m.busy {
                            "Loading tools…"
                        } else {
                            "No tools listed"
                        },
                        "Connect the server and refresh its tools.",
                    ));
                }
                p.child(group(m.tools.iter().map(|tool| {
                    let name = tool.tool_name.clone();
                    let choices = policy_picker(
                        &name,
                        tool.approval_state,
                        tool.team_state,
                        m.busy || !server.is_owner || tool.locked,
                        cx,
                        {
                            let name = name.clone();
                            move |s, policy, w, cx| {
                                s.mcp_request(
                                    Operation::SetPolicy {
                                        id,
                                        name: name.clone(),
                                        policy,
                                    },
                                    w,
                                    cx,
                                )
                            }
                        },
                    );
                    item(
                        tool_title(&tool.tool_name),
                        tool.description.clone(),
                        choices,
                    )
                    .into_any_element()
                })))
            }
            Screen::List => {
                let refresh = control("refresh-servers", "Refresh", false, cx, |s, w, cx| {
                    s.mcp_request(Operation::Browse, w, cx)
                })
                .disabled(m.busy);
                let mut p = notice(page.child(header(
                    "MCP servers",
                    "Manage the services and tools connected to your PostHog account.",
                    Some(refresh.into_any_element()),
                )))
                .child(section("Installed servers", "", None, true));
                if m.servers.is_empty() {
                    p = p.child(empty(
                        if m.busy {
                            "Loading servers…"
                        } else if m.loaded {
                            "No installed servers"
                        } else {
                            "Installations unavailable"
                        },
                        "Add a server from the catalog or connect a custom endpoint.",
                    ));
                } else {
                    p = p.child(group(m.servers.iter().map(|server| {
                        let id = server.id;

                        let (label, tone) = state(server, m.failures.contains_key(&id));
                        suggestion_with(
                            format!("server-{id}"),
                            logo_tile().child(meep_render::brands::logo(&server.name, 21.)),
                            server.name.clone(),
                            format!("{} · {} tools", host(&server.url), server.tool_count),
                            Some(status_mark(label, tone).into_any_element()),
                        )
                        .on_click(cx.listener(move |s, _, w, cx| {
                            if !s.mcp.busy {
                                s.mcp.screen = Screen::Detail(id);
                                s.mcp.tools.clear();
                                s.mcp.confirm = false;
                                s.mcp_request(Operation::Tools { id, refresh: false }, w, cx);
                                cx.notify()
                            }
                        }))
                        .into_any_element()
                    })))
                }
                p.child(self.mcp_browse(cx))
            }
        }
    }
}

impl Desktop {
    /// The PostHog store, searchable and grouped by category, with what is already installed.
    fn mcp_browse(&self, cx: &Context<Self>) -> Div {
        let m = &self.mcp;
        let query = m.search.read(cx).value().trim().to_owned();
        let installed = |t: &Template| m.servers.iter().find(|s| s.template_id == Some(t.id));
        let key_of = |t: &Template| t.category.clone().unwrap_or_default();
        // Categories in the store's order of size, "Other" last.
        let mut categories: Vec<(String, usize)> = vec![];
        for t in &m.catalog {
            let k = key_of(t);
            match categories.iter_mut().find(|(c, _)| *c == k) {
                Some((_, n)) => *n += 1,
                None => categories.push((k, 1)),
            }
        }
        categories.sort_by(|a, b| {
            (
                a.0.is_empty() || a.0 == "other",
                std::cmp::Reverse(a.1),
                category_name(&a.0),
            )
                .cmp(&(
                    b.0.is_empty() || b.0 == "other",
                    std::cmp::Reverse(b.1),
                    category_name(&b.0),
                ))
        });
        let shown: Vec<&Template> = m
            .catalog
            .iter()
            .filter(|t| m.category.as_ref().is_none_or(|c| key_of(t) == *c))
            .filter(|t| query.is_empty() || matches_query(t, &query))
            .collect();
        let row = |t: &Template| {
            let id = t.id;
            let key = t.auth_type == "api_key";
            let trailing = match installed(t) {
                Some(server) => {
                    let (label, tone) = state(server, m.failures.contains_key(&server.id));
                    ui::row()
                        .gap(px(12.))
                        .child(status_mark(label, tone))
                        .child(
                            Icon::new(Glyph::ChevronRight)
                                .size(px(14.))
                                .text_color(rgb(ui::theme::color(ui::TERTIARY))),
                        )
                        .into_any_element()
                }
                None => control(
                    format!("install-{id}"),
                    if key { "Add key" } else { "Connect" },
                    false,
                    cx,
                    move |s, w, cx| {
                        if key {
                            s.mcp.screen = Screen::TemplateKey(id);
                            s.mcp.message = None;
                            s.mcp.key = key_field(w, cx);
                        } else {
                            s.mcp_request(Operation::Template { id, api_key: None }, w, cx)
                        }
                    },
                )
                .disabled(m.busy)
                .into_any_element(),
            };
            let manage = installed(t).map(|s| s.id);
            // Only an installed row opens; the others act from their button alone.
            ui::row()
                .id(SharedString::from(format!("store-{id}")))
                .aria_label(t.name.clone())
                .w_full()
                .h(px(60.))
                .px(px(16.))
                .gap(px(12.))
                .when(manage.is_some(), |r| {
                    r.role(Role::Button)
                        .cursor_pointer()
                        .hover(|s| s.bg(ui::ink(0x05)))
                })
                .child(logo_tile().child(meep_render::brands::logo(&t.name, 21.)))
                .child(
                    meep_shell::settings::copy(
                        t.name.clone(),
                        if t.description.is_empty() {
                            host(&t.url)
                        } else {
                            t.description.clone()
                        },
                    )
                    .flex_1()
                    .min_w_0(),
                )
                .child(div().flex_none().child(trailing))
                .on_click(cx.listener(move |s, _, w, cx| {
                    // An installed server opens to manage; the rest connect from their button.
                    if let Some(id) = manage
                        && !s.mcp.busy
                    {
                        s.mcp.screen = Screen::Detail(id);
                        s.mcp.tools.clear();
                        s.mcp.confirm = false;
                        s.mcp_request(Operation::Tools { id, refresh: false }, w, cx);
                        cx.notify()
                    }
                }))
                .into_any_element()
        };
        let chip = |id: String, label: String, count: usize, on: bool, pick: Option<String>| {
            ui::row()
                .id(SharedString::from(id))
                .role(Role::RadioButton)
                .aria_selected(on)
                .flex_none()
                .h(px(26.))
                .px(px(10.))
                .gap(px(6.))
                .rounded_full()
                .cursor_pointer()
                .text_size(px(12.))
                .font_weight(FontWeight::MEDIUM)
                .text_color(rgb(ui::theme::color(if on {
                    ui::INK
                } else {
                    ui::SECONDARY
                })))
                .when(on, |c| c.bg(ui::ink(0x12)))
                .when(!on, |c| c.hover(|s| s.bg(ui::ink(0x08))))
                .child(label)
                .child(
                    div()
                        .font_weight(FontWeight::NORMAL)
                        .text_color(rgb(ui::theme::color(ui::TERTIARY)))
                        .child(count.to_string()),
                )
                .on_click(cx.listener(move |s, _, _, cx| {
                    s.mcp.category = pick.clone();
                    cx.notify()
                }))
        };
        let chips = ui::row()
            .flex_wrap()
            .gap(px(4.))
            .child(chip(
                "store-all".into(),
                "All".into(),
                m.catalog.len(),
                m.category.is_none(),
                None,
            ))
            .children(categories.iter().map(|(k, n)| {
                chip(
                    format!("store-category-{k}"),
                    category_name(k),
                    *n,
                    m.category.as_deref() == Some(k.as_str()),
                    Some(k.clone()),
                )
            }));
        let search = Input::new(&m.search)
            .aria_label("Search MCP servers")
            .prefix(
                Icon::new(Glyph::Search)
                    .size(px(14.))
                    .text_color(rgb(ui::theme::color(ui::TERTIARY))),
            )
            .cleanable(true)
            .h(px(36.))
            .rounded(px(18.))
            .w_full();
        let mut page = ui::column()
            .child(section(
                "Browse",
                if m.catalog.is_empty() {
                    String::new()
                } else {
                    format!("{} servers in the PostHog store", m.catalog.len())
                },
                Some(
                    control("custom-server", "Custom server", false, cx, |s, w, cx| {
                        s.mcp.screen = Screen::Custom;
                        s.mcp.oauth = true;
                        s.mcp.message = None;
                        for field in [&s.mcp.name, &s.mcp.url, &s.mcp.key] {
                            field.update(cx, |v, cx| v.set_value("", w, cx));
                        }
                    })
                    .disabled(m.busy)
                    .into_any_element(),
                ),
                false,
            ))
            .child(div().pb(px(10.)).child(search))
            .when(categories.len() > 1, |p| {
                p.child(div().pb(px(14.)).child(chips))
            });
        if m.catalog.is_empty() {
            return page.child(empty(
                if m.busy {
                    "Loading the store…"
                } else {
                    "The store is empty"
                },
                "Connect a custom server by its address instead.",
            ));
        }
        if shown.is_empty() {
            return page.child(empty(
                "No servers match",
                if query.is_empty() {
                    "Nothing in this category yet.".to_owned()
                } else {
                    format!("Nothing in the store matches “{query}”. Try another word, or add a custom server.")
                },
            ));
        }
        // Browsing everything reads by category; a search or a category is one list.
        if query.is_empty() && m.category.is_none() && categories.len() > 1 {
            for (k, _) in &categories {
                let rows: Vec<_> = shown
                    .iter()
                    .filter(|t| key_of(t) == *k)
                    .map(|t| row(t))
                    .collect();
                page = page
                    .child(
                        div()
                            .pt(px(8.))
                            .pb(px(6.))
                            .text_size(px(11.5))
                            .font_weight(FontWeight::MEDIUM)
                            .text_color(rgb(ui::theme::color(ui::SECONDARY)))
                            .child(category_name(k)),
                    )
                    .child(div().pb(px(12.)).child(group(rows)));
            }
            page
        } else {
            page.child(group(shown.iter().map(|t| row(t))))
        }
    }
}
/// A server's status and its tone; a failed tool refresh outranks the rest.
fn state(server: &Installed, failed: bool) -> (&'static str, Tone) {
    if failed {
        ("Error", Tone::Danger)
    } else if !server.is_enabled {
        ("Disabled in PostHog", Tone::Neutral)
    } else if server.pending_oauth || server.needs_reauth {
        ("Needs sign-in", Tone::Warning)
    } else {
        ("Connected", Tone::Positive)
    }
}
