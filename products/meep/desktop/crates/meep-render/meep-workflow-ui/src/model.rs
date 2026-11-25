use super::*;

struct Builder<'a> {
    trace: &'a Value,
    traced: bool,
    live: bool,
    data_steps: usize,
}

/// What a group of steps amounts to: any failure fails it; anything that ran
/// counts as ran; only if nothing ran is it skipped.
fn combine(statuses: impl IntoIterator<Item = Status>) -> Status {
    let all: Vec<Status> = statuses.into_iter().collect();
    for s in [
        Status::Failed,
        Status::Running,
        Status::Recovered,
        Status::Ok,
        Status::Skipped,
    ] {
        if all.contains(&s) {
            return s;
        }
    }
    Status::Unknown
}
fn times(n: u64) -> String {
    match n {
        1 => "once".into(),
        2 => "twice".into(),
        n => format!("{n} times"),
    }
}
fn data_kind(kind: &str) -> bool {
    matches!(kind, "command" | "expression")
}
fn save_kind(kind: &str) -> bool {
    matches!(kind, "state" | "dataset")
}
fn ms(value: &Value) -> Option<f64> {
    value.as_f64()
}

impl Builder<'_> {
    fn node(&self, id: &str) -> &Value {
        &self.trace["nodes"][id]
    }
    fn status_of(&self, id: &str) -> Status {
        if !self.traced {
            return Status::Unknown;
        }
        let n = self.node(id);
        let started = n["started"].as_u64().unwrap_or(0);
        let failed = n["failed"].as_u64().unwrap_or(0);
        let recovered = n["recovered"].as_u64().unwrap_or(0);
        let finished =
            n["completed"].as_u64().unwrap_or(0) + failed + n["skipped"].as_u64().unwrap_or(0);
        if self.live && started > finished {
            Status::Running
        } else if started == 0 {
            Status::Skipped
        } else if failed > recovered {
            Status::Failed
        } else if recovered > 0 {
            Status::Recovered
        } else {
            Status::Ok
        }
    }
    fn started(&self, id: &str) -> u64 {
        self.node(id)["started"].as_u64().unwrap_or(0)
    }
    /// Time spent; for a step still running, the time since it started.
    fn elapsed(&self, id: &str) -> Option<f64> {
        if self.status_of(id) == Status::Running {
            let now = ms(&self.trace["elapsedMs"]).unwrap_or(0.);
            return self.start(id).map(|start| (now - start).max(0.));
        }
        ms(&self.node(id)["elapsedMs"])
    }
    /// When the step first started, if the runner recorded it.
    fn start(&self, id: &str) -> Option<f64> {
        ms(&self.node(id)["startMs"])
    }
    /// How many times a loop ran: the most any of its direct steps started.
    fn iterations(&self, step: &Value) -> u64 {
        step["steps"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|s| self.started(s["id"].as_str().unwrap_or("")))
            .max()
            .unwrap_or(0)
    }

    /// A step's own name, or one made from what it does.
    fn title(step: &Value) -> String {
        if let Some(t) = step["title"].as_str().filter(|t| !t.trim().is_empty()) {
            return t.to_owned();
        }
        let tool = step["tool"].as_str().unwrap_or("");
        let source = step["source"].as_str().unwrap_or("");
        match step["kind"].as_str().unwrap_or("") {
            "source" if tool.is_empty() || tool == "exec" => format!("Query {source}"),
            "source" => format!("{} in {source}", human_name(tool)),
            "cli" => {
                let args: Vec<&str> = step["args"]
                    .as_array()
                    .map(|a| a.iter().filter_map(Value::as_str).take(3).collect())
                    .unwrap_or_default();
                let permit = step["permit"].as_str().unwrap_or("command");
                if args.is_empty() {
                    format!("Run {permit}")
                } else {
                    format!("{permit} {}", args.join(" "))
                }
            }
            "notify" => "Send a notification".into(),
            "ai" => "Ask AI".into(),
            "agent" => "Run agent".into(),
            "state" => "Update saved state".into(),
            "dataset" => "Save to a dataset".into(),
            "merge" => "Join data".into(),
            "command" => "Custom JavaScript".into(),
            "expression" => "Transform data".into(),
            _ => human_name(step["id"].as_str().unwrap_or("step")),
        }
    }

    fn action(&mut self, step: &Value, ctx: &Ctx, at: f64) -> Row {
        let id = step["id"].as_str().unwrap_or("").to_owned();
        let kind = step["kind"].as_str().unwrap_or("");
        let source = step["source"].as_str().unwrap_or("");
        let permit = step["permit"].as_str().unwrap_or("");
        let tile = match kind {
            "source" if !source.is_empty() => Tile::Brand(source.into(), "mcp"),
            "cli" if !permit.is_empty() => Tile::Brand(permit.into(), "cli"),
            _ => Tile::Glyph(step_glyph(kind)),
        };
        let mut row = Row::new(id.clone(), Self::title(step), tile);
        row.uses = match kind {
            "source" => Some(match step["tool"].as_str() {
                Some(tool) if !tool.is_empty() => format!("{source} · {}", human_name(tool)),
                _ => source.to_owned(),
            }),
            "cli" => Some(permit.to_owned()),
            _ => None,
        };
        if let Some(uses) = &row.uses
            && kind == "cli"
        {
            row.meta.push(uses.clone());
        } else if kind == "source" && !source.is_empty() {
            row.meta.push(source.to_owned());
        }
        row.status = self.status_of(&id);
        row.started = self.started(&id);
        row.elapsed = self.elapsed(&id);
        row.start = self.start(&id).unwrap_or(at);
        row.error = self.node(&id)["error"].as_str().map(str::to_owned);
        row.recovery = ctx.recovery.clone();
        row.guard = ctx.guard.clone();
        row.edit = Some(id.clone());
        if let Some(n) = ctx.iterations {
            row.looped = true;
            if self.traced && n > 0 {
                row.meta.push(if row.started < n {
                    format!("{} of {n} times", row.started)
                } else {
                    times(row.started)
                });
            }
        } else if row.started > 1 {
            row.meta.push(times(row.started));
        }
        if ctx.guard.is_some() {
            row.meta.push("conditional".into());
        }
        row
    }

    /// The visible rows of a list of steps, in order, with their start times.
    fn flatten(&mut self, steps: &[Value], ctx: &Ctx, mut at: f64, rows: &mut Vec<Row>) -> f64 {
        let mut pending: Vec<String> = vec![];
        for step in steps {
            let id = step["id"].as_str().unwrap_or("").to_owned();
            let kind = step["kind"].as_str().unwrap_or("");
            let elapsed = self.elapsed(&id);
            let begin = rows.len();
            match kind {
                k if data_kind(k) => {
                    self.data_steps += 1;
                    let named = step["title"].as_str().is_some_and(|t| !t.trim().is_empty());
                    // Untitled data steps say what they're for by where they sit.
                    let title = if named {
                        Self::title(step)
                    } else if rows.iter().any(|r| !r.data_row) {
                        "Shape the result".into()
                    } else {
                        "Prepare the request".into()
                    };
                    pending.push(title.clone());
                    let mut row = self.action(step, ctx, at);
                    row.title = title.clone();
                    row.data_row = true;
                    row.tile = Tile::Glyph(Glyph::Braces);
                    row.meta = vec!["data step".into()];
                    if row.status == Status::Ok
                        && ctx.iterations.is_none()
                        && row.elapsed.is_some_and(|e| e > 1000.)
                    {
                        row.meta.push("slow".into());
                    }
                    rows.push(row);
                }
                "try" => {
                    let caught: Vec<String> = step["catch"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .map(Self::title)
                        .collect();
                    let mut inner = ctx.clone();
                    inner.recovery = Some(if caught.is_empty() {
                        "Continues without it".into()
                    } else {
                        caught.join(", ")
                    });
                    let mut sub = vec![];
                    self.flatten(
                        step["steps"].as_array().map(Vec::as_slice).unwrap_or(&[]),
                        &inner,
                        at,
                        &mut sub,
                    );
                    // A fallback that actually ran is worth a row of its own.
                    let catch = step["catch"].as_array().cloned().unwrap_or_default();
                    if catch
                        .iter()
                        .any(|c| self.started(c["id"].as_str().unwrap_or("")) > 0)
                    {
                        let mut fallback = Row::new(
                            format!("{id}-fallback"),
                            format!(
                                "Used fallback: {}",
                                inner.recovery.clone().unwrap_or_default()
                            ),
                            Tile::Glyph(Glyph::LifeBuoy),
                        );
                        fallback.status = Status::Recovered;
                        fallback.start = at;
                        sub.push(fallback);
                    }
                    rows.extend(sub);
                }
                "if" => {
                    let then = step["then"].as_array().cloned().unwrap_or_default();
                    let otherwise = step["else"].as_array().cloned().unwrap_or_default();
                    let title = Self::title(step);
                    if otherwise.is_empty()
                        && !then.is_empty()
                        && then
                            .iter()
                            .all(|s| save_kind(s["kind"].as_str().unwrap_or("")))
                        && then.len() > 1
                    {
                        // Several saves behind one guard: one row, named by the guard.
                        let first = &then[0];
                        let mut row = self.action(first, ctx, at);
                        row.key = id.clone();
                        row.title = title.trim_end_matches(" only").to_owned();
                        row.tile = Tile::Glyph(Glyph::Database);
                        row.meta = vec![format!("{} writes", then.len()), "conditional".into()];
                        row.guard = Some(title.clone());
                        row.status = combine(
                            then.iter()
                                .map(|s| self.status_of(s["id"].as_str().unwrap_or(""))),
                        );
                        row.calls = then
                            .iter()
                            .map(|s| Call {
                                title: Self::title(s),
                                started: self.started(s["id"].as_str().unwrap_or("")),
                                elapsed: self.elapsed(s["id"].as_str().unwrap_or("")).unwrap_or(0.),
                            })
                            .collect();
                        row.elapsed = elapsed;
                        rows.push(row);
                    } else if otherwise.is_empty() {
                        let mut inner = ctx.clone();
                        inner.guard = Some(title);
                        self.flatten(&then, &inner, at, rows);
                    } else if ctx.depth == 0 {
                        let mut group =
                            Row::new(id.clone(), title.clone(), Tile::Glyph(Glyph::GitBranch));
                        group.status = self.status_of(&id);
                        group.start = self.start(&id).unwrap_or(at);
                        group.elapsed = elapsed;
                        group.edit = Some(id.clone());
                        let took_then = then
                            .iter()
                            .any(|s| self.started(s["id"].as_str().unwrap_or("")) > 0);
                        let took_else = otherwise
                            .iter()
                            .any(|s| self.started(s["id"].as_str().unwrap_or("")) > 0);
                        group.meta.push(match (took_then, took_else) {
                            (true, _) => "took Yes".into(),
                            (_, true) => "took No".into(),
                            _ => "condition".into(),
                        });
                        let mut inner = ctx.clone();
                        inner.depth = 1;
                        for (lane, steps) in [("Yes", &then), ("No", &otherwise)] {
                            let mut sub = vec![];
                            self.flatten(steps, &inner, at, &mut sub);
                            for mut r in sub {
                                r.meta.insert(0, format!("if {}", lane.to_lowercase()));
                                group.children.push(r);
                            }
                        }
                        rows.push(group);
                    } else {
                        let mut inner = ctx.clone();
                        inner.guard = Some(title);
                        self.flatten(&then, &inner, at, rows);
                        self.flatten(&otherwise, &inner, at, rows);
                    }
                }
                "map" => {
                    let n = self.iterations(step);
                    let mut inner = ctx.clone();
                    inner.iterations = Some(n);
                    if ctx.depth == 0 {
                        let mut group = Row::new(
                            id.clone(),
                            Self::title(step),
                            Tile::Glyph(Glyph::ListChecks),
                        );
                        group.status = self.status_of(&id);
                        group.start = self.start(&id).unwrap_or(at);
                        group.elapsed = elapsed;
                        group.edit = Some(id.clone());
                        group.meta.push(if self.traced {
                            format!("for each · {n} {}", if n == 1 { "item" } else { "items" })
                        } else {
                            "for each item".into()
                        });
                        group.recovery = ctx.recovery.clone();
                        group.guard = ctx.guard.clone();
                        inner.depth = 1;
                        self.flatten(
                            step["steps"].as_array().map(Vec::as_slice).unwrap_or(&[]),
                            &inner,
                            at,
                            &mut group.children,
                        );
                        // The group already says it; children don't repeat it.
                        for child in &mut group.children {
                            if child.recovery == group.recovery {
                                child.recovery = None;
                            }
                        }
                        let visible: Vec<usize> = (0..group.children.len())
                            .filter(|i| !group.children[*i].data_row)
                            .collect();
                        if visible.len() == 1 {
                            // A loop around one step reads as that step, done for each item.
                            let only = group.children.remove(visible[0]);
                            group.tile = only.tile.clone();
                            group.uses = only.uses.clone();
                            group.meta = only
                                .meta
                                .iter()
                                .filter(|m| !m.contains("time") && *m != "once" && *m != "twice")
                                .cloned()
                                .collect();
                            group.meta.push(if !self.traced {
                                "for each item".into()
                            } else if n == 1 {
                                "for 1 item".into()
                            } else {
                                format!("for each of {n}")
                            });
                            group.calls = vec![Call {
                                title: only.title.clone(),
                                started: only.started,
                                elapsed: only.elapsed.unwrap_or(0.),
                            }];
                            group.data.extend(
                                group
                                    .children
                                    .iter()
                                    .filter(|r| r.data_row)
                                    .map(|r| r.title.clone()),
                            );
                            group.children.retain(|r| !r.data_row);
                        }
                        rows.push(group);
                    } else {
                        self.flatten(
                            step["steps"].as_array().map(Vec::as_slice).unwrap_or(&[]),
                            &inner,
                            at,
                            rows,
                        );
                    }
                }
                "parallel" => {
                    let branches = step["branches"].as_array().cloned().unwrap_or_default();
                    if ctx.depth == 0 {
                        let mut group =
                            Row::new(id.clone(), Self::title(step), Tile::Glyph(Glyph::Layers));
                        group.status = self.status_of(&id);
                        group.start = self.start(&id).unwrap_or(at);
                        group.elapsed = elapsed;
                        group.edit = Some(id.clone());
                        group.meta.push(format!("{} in parallel", branches.len()));
                        group.recovery = ctx.recovery.clone();
                        group.guard = ctx.guard.clone();
                        for (index, branch) in branches.iter().enumerate() {
                            group
                                .children
                                .push(self.branch(&id, index, branch, ctx, at));
                        }
                        rows.push(group);
                    } else {
                        for branch in &branches {
                            self.flatten(
                                branch["steps"].as_array().map(Vec::as_slice).unwrap_or(&[]),
                                ctx,
                                at,
                                rows,
                            );
                        }
                    }
                }
                "merge" => {
                    let mut row = self.action(step, ctx, at);
                    row.tile = Tile::Glyph(Glyph::GitMerge);
                    rows.push(row);
                }
                k if save_kind(k) => {
                    let row = self.action(step, ctx, at);
                    // Back-to-back saves under the same conditions read as one.
                    if let Some(last) = rows.last_mut().filter(|r| {
                        !r.data_row
                            && r.children.is_empty()
                            && matches!(r.tile, Tile::Glyph(Glyph::Database))
                            && r.guard == row.guard
                            && r.recovery == row.recovery
                            && ctx.iterations.is_none()
                    }) {
                        let writes = last.calls.len().max(1) + 1;
                        if last.calls.is_empty() {
                            last.calls.push(Call {
                                title: last.title.clone(),
                                started: last.started,
                                elapsed: last.elapsed.unwrap_or(0.),
                            });
                        }
                        last.calls.push(Call {
                            title: row.title.clone(),
                            started: row.started,
                            elapsed: row.elapsed.unwrap_or(0.),
                        });
                        last.meta.retain(|m| !m.ends_with("writes"));
                        last.meta.insert(0, format!("{writes} writes"));
                        last.status = combine([last.status, row.status]);
                        last.elapsed = Some(last.elapsed.unwrap_or(0.) + row.elapsed.unwrap_or(0.));
                    } else {
                        let mut row = row;
                        row.tile = Tile::Glyph(Glyph::Database);
                        rows.push(row);
                    }
                }
                _ => rows.push(self.action(step, ctx, at)),
            }
            // Data steps count toward the first visible row they feed.
            if !pending.is_empty()
                && let Some(row) = rows[begin..].iter_mut().find(|r| !r.data_row)
            {
                row.data.append(&mut pending);
            }
            if ctx.iterations.is_none() {
                at += elapsed.unwrap_or(0.);
            }
        }
        // Trailing data steps belong to the last visible row.
        if !pending.is_empty()
            && let Some(row) = rows.iter_mut().rev().find(|r| !r.data_row)
        {
            row.data.append(&mut pending);
        }
        at
    }

    /// One parallel branch as a single row: its name, the calls it made and
    /// how long it took.
    fn branch(&mut self, parent: &str, index: usize, branch: &Value, ctx: &Ctx, at: f64) -> Row {
        let steps = branch["steps"].as_array().cloned().unwrap_or_default();
        let mut inner = ctx.clone();
        inner.depth = 1;
        let mut sub = vec![];
        let end = self.flatten(&steps, &inner, at, &mut sub);
        let visible: Vec<&Row> = sub.iter().filter(|r| !r.data_row).collect();
        let title = branch["title"]
            .as_str()
            .filter(|t| !t.is_empty())
            .map(str::to_owned)
            .or_else(|| visible.first().map(|r| r.title.clone()))
            .unwrap_or_else(|| format!("Branch {}", index + 1));
        let main = visible
            .iter()
            .find(|r| matches!(r.tile, Tile::Brand(..)))
            .or(visible.first());
        let mut row = Row::new(
            format!(
                "{parent}-{}",
                branch["id"].as_str().unwrap_or(&index.to_string())
            ),
            title
                .split(" · optional")
                .next()
                .unwrap_or(&title)
                .to_owned(),
            main.map(|r| r.tile.clone())
                .unwrap_or(Tile::Glyph(Glyph::Layers)),
        );
        if let Some(main) = main
            && let Some(uses) = &main.uses
        {
            row.meta.push(if visible.len() == 1 {
                main.title.clone()
            } else {
                uses.split(" · ").next().unwrap_or(uses).to_owned()
            });
        }
        let calls: u64 = visible
            .iter()
            .filter(|r| r.uses.is_some())
            .map(|r| r.started)
            .sum();
        if self.traced && calls > 1 {
            row.meta.push(format!("{calls} calls"));
        }
        if title.contains("optional") {
            row.meta.push("optional".into());
        }
        row.recovery = visible.iter().find_map(|r| r.recovery.clone());
        row.status = combine(sub.iter().filter(|r| !r.data_row).map(|r| r.status));
        let first = sub
            .iter()
            .filter(|r| r.started > 0 || r.status == Status::Running)
            .map(|r| r.start)
            .fold(f64::INFINITY, f64::min);
        row.start = if first.is_finite() { first } else { at };
        // Wall time: the branch's own top-level steps, which already
        // contain their loops; never the time added up across calls.
        let wall: f64 = steps
            .iter()
            .filter_map(|s| self.elapsed(s["id"].as_str().unwrap_or("")))
            .sum();
        let _ = end;
        row.elapsed = Some(wall).filter(|e| *e > 0. || self.traced);
        row.error = sub.iter().find_map(|r| r.error.clone());
        row.calls = visible
            .iter()
            .map(|r| Call {
                title: r.title.clone(),
                started: r.started,
                elapsed: r.elapsed.unwrap_or(0.),
            })
            .collect();
        row.data = sub
            .iter()
            .filter(|r| r.data_row)
            .map(|r| r.title.clone())
            .collect();
        row.edit = visible.first().and_then(|r| r.edit.clone());
        row
    }
}

pub(super) fn model(definition: &Value, trace: &Value) -> Model {
    let traced = trace["nodes"].is_object();
    let live = trace["live"] == true;
    let mut b = Builder {
        trace,
        traced,
        live,
        data_steps: 0,
    };
    let steps = definition["steps"].as_array().cloned().unwrap_or_default();
    let mut rows = vec![];
    let mut failure = None;
    let mut failure_ran = false;
    // A recovery wrapper around the whole run is what happens on failure.
    if steps.len() == 1 && steps[0]["kind"] == "try" {
        let wrapper = &steps[0];
        let catch = wrapper["catch"].as_array().cloned().unwrap_or_default();
        failure = Some(
            catch
                .iter()
                .map(|c| Builder::title(c).to_lowercase())
                .collect::<Vec<_>>()
                .join(", then "),
        )
        .filter(|s| !s.is_empty());
        failure_ran = catch
            .iter()
            .any(|c| b.started(c["id"].as_str().unwrap_or("")) > 0);
        for c in &catch {
            if data_kind(c["kind"].as_str().unwrap_or("")) {
                b.data_steps += 1;
            }
        }
        b.flatten(
            wrapper["steps"]
                .as_array()
                .map(Vec::as_slice)
                .unwrap_or(&[]),
            &Ctx::default(),
            0.,
            &mut rows,
        );
    } else {
        b.flatten(&steps, &Ctx::default(), 0., &mut rows);
    }
    let total = ms(&trace["elapsedMs"]).unwrap_or_else(|| {
        rows.iter()
            .map(|r| r.start + r.elapsed.unwrap_or(0.))
            .fold(0., f64::max)
    });
    Model {
        rows,
        failure,
        failure_ran,
        data_steps: b.data_steps,
        total,
        traced,
        live,
    }
}
