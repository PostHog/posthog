//! Topic MCP tools for the inbox, the task board and topic files. Every change is a topic
//! command or an engine transition that applies topic policy, so an agent can propose work
//! but never approve it, and anything that needs the person waits in Needs You.
use crate::{
    Server,
    topic_mcp::{Caller, input},
};
use anyhow::{Context, Result, bail, ensure};
use meep_topic::{Column, Task, TaskId, Thread, ThreadId, ThreadState, TopicId};
use serde::Deserialize;
use serde_json::{Value, json};
use uuid::Uuid;

/// Largest file `read_file` returns and `write_file` accepts.
const MAX_FILE: usize = 256 * 1024;

pub(super) fn tools() -> Vec<Value> {
    let text = json!({"type":"string"});
    let id = json!({"type":"string","format":"uuid"});
    vec![
        crate::mcp::tool(
            "list_threads",
            "List agent-published reports in the topic inbox with their priority, impact and status: open, or resolved or dismissed with the person's reason. Check it before publishing so you never repeat an open report or one the person dismissed.",
            json!({"limit":{"type":"integer","minimum":1,"maximum":200}}),
            &[],
        ),
        crate::mcp::tool(
            "get_thread",
            "Read an authorized topic thread, including report evidence, linked tasks and any legacy review details.",
            json!({"thread":id}),
            &["thread"],
        ),
        crate::mcp::tool(
            "list_tasks",
            "List tasks on the board, optionally in one column.",
            json!({"column":{"enum":["todo","in_progress","needs_you","done"]}}),
            &[],
        ),
        crate::mcp::tool(
            "get_task",
            "Read one task with its proposed action, draft, result and log.",
            json!({"task":id}),
            &["task"],
        ),
        crate::mcp::tool(
            "plan_task",
            "Add a task only for work that should not happen now in this conversation. for: \"you\" is side work the person does themselves; \"later\" is work you pick up yourself in this conversation when you are free; \"sub_agent\" starts a separate agent run, only for work that is completely separate and long enough to need its own run. Do the work here instead whenever you can.",
            json!({"title":text,"brief":text,"for":{"enum":["you","later","sub_agent"]}}),
            &["title", "for"],
        ),
        crate::mcp::tool(
            "move_task",
            "Move a task between To do, In progress and Done, or to Needs you. Use ask_user for input on the current task. Tasks waiting in Needs you stay there for the person.",
            json!({"task":id,"column":{"enum":["todo","in_progress","needs_you","done"]}}),
            &["task", "column"],
        ),
        crate::mcp::tool(
            "complete_task",
            "Mark a To do or In progress task done. Work that waits for approval cannot be completed this way.",
            json!({"task":id}),
            &["task"],
        ),
        crate::mcp::tool(
            "send_back",
            "Withdraw a proposed action waiting in Needs you and return the task for revision with a note.",
            json!({"task":id,"note":text}),
            &["task", "note"],
        ),
        crate::mcp::tool(
            "list_files",
            "List the topic's files with their latest revision.",
            json!({}),
            &[],
        ),
        crate::mcp::tool(
            "read_file",
            "Read a UTF-8 text file, optionally at an earlier revision.",
            json!({"path":text,"revision":{"type":"integer","minimum":1}}),
            &["path"],
        ),
        crate::mcp::tool(
            "write_file",
            "Write a UTF-8 text file as a new revision. expected_revision is the revision you read, or 0 for a new file; a stale value is refused.",
            json!({"path":text,"text":text,"expected_revision":{"type":"integer","minimum":0}}),
            &["path", "text", "expected_revision"],
        ),
    ]
}

/// Run a work tool on `topic` (the caller's own topic for changes), or `None` when the name
/// belongs to another tool set.
pub(super) async fn call(
    s: &Server,
    caller: &Caller,
    topic: TopicId,
    name: &str,
    args: Value,
) -> Option<Result<Value>> {
    Some(match name {
        "list_threads" => threads(s, topic, args),
        "get_thread" => get_thread(s, topic, args),
        "list_tasks" => tasks(s, topic, args),
        "get_task" => get_task(s, topic, args),
        "plan_task" => plan_task(s, topic, args).await,
        "move_task" => move_task(s, topic, args).await,
        "complete_task" => complete(s, topic, args).await,
        "send_back" => send_back(s, topic, args).await,
        "list_files" => files(s, topic, args).await,
        "read_file" => read_file(s, topic, args).await,
        "write_file" => write_file(s, caller, topic, args).await,
        _ => return None,
    })
}

fn state_json(state: &ThreadState) -> Value {
    match state {
        ThreadState::Sorting => json!({"state":"sorting"}),
        ThreadState::NeedsYou { reason, .. } => json!({"state":"needs_you","reason":reason}),
        ThreadState::Handled => json!({"state":"handled"}),
        ThreadState::Skipped { reason, rule } => {
            json!({"state":"skipped","reason":reason,"rule":rule})
        }
    }
}

fn thread_summary(t: &Thread) -> Value {
    let mut v = json!({
        "id":t.id,
        "subject":t.subject,
        "summary":t.summary,
        "unseen":t.unseen,
        "messages":t.messages.len(),
        "updated_at":t.updated_at,
    });
    merge(&mut v, state_json(&t.state));
    // What a watcher needs to avoid re-reporting: how urgent it was, and whether
    // the person already resolved or dismissed it, and why.
    if let Some(r) = &t.report_sources {
        v["priority"] = json!(r.priority.map(|p| p.label()));
        v["impact"] = json!(r.impact);
        v["status"] = json!(match &r.verdict {
            Some(v) => json!({"outcome": match v.outcome {
                meep_topic::ReportOutcome::Resolved => "resolved",
                meep_topic::ReportOutcome::Dismissed => "dismissed",
            }, "reason": v.reason, "at": v.at}),
            None => json!("open"),
        });
    }
    v
}

fn merge(into: &mut Value, from: Value) {
    if let (Some(a), Value::Object(b)) = (into.as_object_mut(), from) {
        a.extend(b);
    }
}

fn threads(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        limit: Option<usize>,
    }
    let Args { limit } = input(args)?;
    let limit = limit.unwrap_or(50);
    ensure!((1..=200).contains(&limit), "limit must be 1 to 200");
    let mut threads = s.engine.topic(topic)?.threads;
    threads.retain(|t| t.is_agent_report());
    threads.sort_by_key(|t| {
        (
            !matches!(t.state, ThreadState::NeedsYou { .. }),
            std::cmp::Reverse(t.updated_at),
        )
    });
    Ok(json!(
        threads
            .iter()
            .take(limit)
            .map(thread_summary)
            .collect::<Vec<_>>()
    ))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ThreadArg {
    thread: ThreadId,
}

fn get_thread(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    let ThreadArg { thread } = input(args)?;
    let state = s.engine.topic(topic)?;
    let t = state
        .threads
        .iter()
        .find(|t| t.id == thread)
        .context("This topic has no such thread. Use list_threads.")?;
    let mut v = thread_summary(t);
    v["linked_tasks"] = json!(
        state
            .tasks
            .iter()
            .filter(|task| t.links_task(task))
            .map(|task| task.id)
            .collect::<Vec<_>>()
    );
    v["messages"] = json!(
        t.messages
            .iter()
            .map(|m| json!({"id":m.id,"producer":m.producer,"author":m.author,"at":m.at,"source":m.reply_target(),"text":m.text}))
            .collect::<Vec<_>>()
    );
    v["report_sources"] = json!(t.report_sources);
    v["outcomes"] = json!(t.outcomes);
    v["later_questions"] = json!(t.pending_questions.len());
    if let ThreadState::NeedsYou { suggestions, .. } = &t.state {
        v["choices"] = json!(
            suggestions
                .iter()
                .enumerate()
                .map(|(i, s)| json!({"choice":i,"suggestion":s}))
                .collect::<Vec<_>>()
        );
    }
    Ok(v)
}

fn column(name: &str) -> Result<Column> {
    Ok(match name {
        "todo" => Column::Todo,
        "in_progress" => Column::InProgress,
        "needs_you" => Column::NeedsYou,
        "done" => Column::Done,
        other => bail!("Unknown column {other}. Use todo, in_progress, needs_you or done."),
    })
}

fn task_json(t: &Task, log: bool) -> Value {
    let mut v = json!({
        "id":t.id,
        "title":t.title,
        "column":t.column,
        "queued":t.queued,
        "added_by":t.added_by,
        "assignment":t.assignment,
        "awaiting_start_approval":t.review_before_start,
        "action":t.action.as_ref().map(|a| json!({"kind":a.kind,"label":a.label})),
        "input_question":t.input_question,
        "result":t.result,
        "draft":t.draft,
        "worker":t.worker,
        "updated_at":t.updated_at,
    });
    if log {
        v["from_thread"] = json!(t.from_thread);
        v["log"] = json!(t.log);
        v["suggestions"] = json!(t.suggestions);
    }
    v
}

fn tasks(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        column: Option<String>,
    }
    let Args { column: filter } = input(args)?;
    let filter = filter.as_deref().map(column).transpose()?;
    Ok(json!(
        s.engine
            .topic(topic)?
            .tasks
            .iter()
            .filter(|t| filter.is_none_or(|c| t.column == c))
            .map(|t| task_json(t, false))
            .collect::<Vec<_>>()
    ))
}

fn find_task(s: &Server, topic: TopicId, id: TaskId) -> Result<Task> {
    s.engine
        .topic(topic)?
        .tasks
        .into_iter()
        .find(|t| t.id == id)
        .context("This topic has no such task. Use list_tasks.")
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TaskArg {
    task: TaskId,
}

fn get_task(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    let TaskArg { task } = input(args)?;
    Ok(task_json(&find_task(s, topic, task)?, true))
}

/// A task waiting for the person's review stays with the person.
fn reviewable_by_agent(task: &Task) -> Result<()> {
    ensure!(
        task.column != Column::NeedsYou,
        "“{}” is waiting for the person in Needs you. Only they can decide it.",
        task.title
    );
    ensure!(
        !task.review_before_start,
        "“{}” needs the person's approval to start.",
        task.title
    );
    Ok(())
}

async fn move_to(s: &Server, topic: TopicId, task: TaskId, to: Column) -> Result<Value> {
    let current = find_task(s, topic, task)?;
    reviewable_by_agent(&current)?;
    s.engine.move_task(topic, task, to).await?;
    Ok(task_json(&find_task(s, topic, task)?, false))
}

async fn plan_task(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        title: String,
        #[serde(default)]
        brief: String,
        #[serde(rename = "for")]
        owner: String,
    }
    let Args {
        title,
        brief,
        owner,
    } = input(args)?;
    let title = title.trim();
    ensure!(
        !title.is_empty() && title.chars().count() <= 200,
        "title must be 1 to 200 characters"
    );
    let owner = match owner.as_str() {
        "you" => meep_topic::InboxAssignment::Human,
        "later" => meep_topic::InboxAssignment::Session,
        "sub_agent" => meep_topic::InboxAssignment::Investigate,
        other => anyhow::bail!("for must be you, later or sub_agent, not {other}"),
    };
    let task = s.engine.plan_task(topic, title, brief, owner).await?;
    Ok(task_json(&find_task(s, topic, task)?, false))
}

async fn move_task(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        task: TaskId,
        column: String,
    }
    let Args { task, column: to } = input(args)?;
    move_to(s, topic, task, column(&to)?).await
}

async fn complete(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    let TaskArg { task } = input(args)?;
    move_to(s, topic, task, Column::Done).await
}

async fn send_back(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        task: TaskId,
        note: String,
    }
    let Args { task, note } = input(args)?;
    let note = note.trim();
    ensure!(
        !note.is_empty() && note.chars().count() <= 2000,
        "note must be 1 to 2000 characters"
    );
    let current = find_task(s, topic, task)?;
    ensure!(
        current.column == Column::NeedsYou
            && current.action.is_some()
            && !current.review_before_start,
        "Only a proposed action waiting in Needs you can be sent back"
    );
    s.engine.send_back(topic, task, note).await?;
    Ok(task_json(&find_task(s, topic, task)?, false))
}

/// Run a blocking file-store call off the async workers.
async fn blocking<T: Send + 'static>(
    s: &Server,
    f: impl FnOnce(&dyn meep_engine::Blobs) -> Result<T> + Send + 'static,
) -> Result<T> {
    let s = s.clone();
    tokio::task::spawn_blocking(move || f(s.engine.blobs()))
        .await
        .context("File access interrupted")?
}

fn path(path: &str) -> Result<String> {
    let path = path.trim();
    ensure!(
        !path.is_empty()
            && path.len() <= 255
            && !path.starts_with('/')
            && !path.contains('\\')
            && !path.chars().any(char::is_control)
            && path
                .split('/')
                .all(|p| !p.is_empty() && p != "." && p != ".."),
        "path must be a relative file name such as notes/weekly.md"
    );
    Ok(path.into())
}

async fn files(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {}
    let Args {} = input(args)?;
    let listed = blocking(s, move |b| b.list(topic)).await?;
    Ok(json!(
        listed
            .iter()
            .map(|f| json!({"path":f.name,"revision":f.revision,"bytes":f.bytes.len()}))
            .collect::<Vec<_>>()
    ))
}

async fn read_file(s: &Server, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        path: String,
        revision: Option<u64>,
    }
    let Args {
        path: name,
        revision,
    } = input(args)?;
    let name = path(&name)?;
    let lookup = name.clone();
    let blob = blocking(s, move |b| b.get(topic, &lookup, revision))
        .await?
        .with_context(|| format!("{name} has no such revision. Use list_files."))?;
    ensure!(
        blob.bytes.len() <= MAX_FILE,
        "{name} is larger than 256 KiB"
    );
    let text = String::from_utf8(blob.bytes)
        .ok()
        .with_context(|| format!("{name} is not UTF-8 text"))?;
    Ok(json!({"path":name,"revision":blob.revision,"text":text}))
}

async fn write_file(s: &Server, caller: &Caller, topic: TopicId, args: Value) -> Result<Value> {
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Args {
        path: String,
        text: String,
        expected_revision: u64,
    }
    let Args {
        path: name,
        text,
        expected_revision,
    } = input(args)?;
    let name = path(&name)?;
    ensure!(text.len() <= MAX_FILE, "text must be at most 256 KiB");
    let lookup = name.clone();
    let head = blocking(s, move |b| b.get(topic, &lookup, None))
        .await?
        .map_or(0, |b| b.revision);
    ensure!(
        head == expected_revision,
        "{name} is at revision {head}, not {expected_revision}. Read it again before writing."
    );
    let write = s
        .engine
        .write_file(
            topic,
            name.clone(),
            text.into_bytes(),
            Uuid::new_v4(),
            Some(expected_revision),
        )
        .await?;
    // The file shows on the task that wrote it. A missed link never fails the write.
    if let Some(run) = caller.run()
        && let Err(error) = s.engine.record_run_file(topic, run, name.clone()).await
    {
        log::warn!("Could not link {name} to its task: {error:#}");
    }
    if write.competing_with.is_some() {
        bail!(
            "{name} changed while writing. Your text is kept as revision {} and the person will choose in Needs you.",
            write.revision.revision
        );
    }
    Ok(json!({"path":name,"revision":write.revision.revision}))
}
