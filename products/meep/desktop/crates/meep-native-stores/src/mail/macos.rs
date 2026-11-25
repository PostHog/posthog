use super::*;
const MAIL: &str = "com.apple.mail";
/// What an adapter may print; a page is far smaller.
const MAX_OUTPUT: u64 = 4 << 20;

impl MailApp {
    fn require_read(&self) -> Result<()> {
        match self.automation(false)? {
            Automation::Granted => Ok(()),
            Automation::Denied => Err(Failure::Denied.into()),
            Automation::NotDetermined => Err(Failure::Undecided.into()),
            Automation::NotRunning => Err(Failure::NotRunning.into()),
        }
    }
}
impl Mail for MailApp {
    fn automation(&self, ask: bool) -> Result<Automation> {
        crate::bundled("Mail")?;
        consent::determine(MAIL, ask)
    }
    fn mailboxes(&self, deadline: Duration) -> Result<Mailboxes> {
        self.require_read()?;
        run("mailboxes", serde_json::json!({}), deadline)
    }
    fn messages(&self, page: &Page, deadline: Duration) -> Result<Vec<Summary>> {
        page.validate()?;
        self.require_read()?;
        read_page(page, deadline, &chrono::Local, |argv, deadline| {
            // No shell, no interpolation: the source is fixed, the data are
            // its arguments.
            let mut args = vec!["-e", PAGE_ADAPTER];
            args.extend(argv.iter().map(String::as_str));
            let out = osascript(&args, None, deadline)?;
            Ok(String::from_utf8_lossy(&out).into_owned())
        })
    }
    fn message(&self, message: &MessageRef, deadline: Duration) -> Result<Message> {
        message.validate()?;
        self.require_read()?;
        run(
            "message",
            serde_json::json!({ "message": message }),
            deadline,
        )
    }
}

/// One page through the page adapter: `messages` picks it, then `rows`
/// readers fill in its fields, a few at once, and one reader its headers.
/// `run` runs the adapter with an `argv` and a deadline and gives its answer.
fn read_page<Tz: chrono::TimeZone + Sync>(
    page: &Page,
    deadline: Duration,
    zone: &Tz,
    run: impl Fn(&[String], Duration) -> Result<String> + Sync,
) -> Result<Vec<Summary>> {
    let until = std::time::Instant::now()
        .checked_add(deadline)
        .context("Mail reader deadline out of range")?;
    let left = || until.saturating_duration_since(std::time::Instant::now());
    let (plan, rows) = parse_plan(
        &run(&page_args(page, zone.clone(), deadline), deadline)?,
        deadline,
    )?;
    let Some(plan) = plan else {
        return Ok(vec![]);
    };
    let ids: Vec<String> = rows.iter().map(|r| r[0].clone()).collect();
    let ids: Vec<&str> = ids.iter().map(String::as_str).collect();
    let read = |what: &str, ids: &[&str], deadline: Duration| {
        parse_rows(
            &run(&rows_args(&plan, what, ids, deadline), deadline)?,
            what,
            deadline,
        )
    };
    // The fields, a few readers at once: Mail answers each reader a frame
    // apart, but every waiting reader in the same frame.
    let deadline = left();
    let fields: Vec<Result<Vec<Vec<String>>>> = std::thread::scope(|scope| {
        let handles: Vec<_> = ids
            .chunks(ids.len().div_ceil(readers(ids.len())))
            .map(|chunk| {
                let read = &read;
                scope.spawn(move || read("fields", chunk, deadline))
            })
            .collect();
        handles
            .into_iter()
            .map(|h| {
                h.join()
                    .unwrap_or_else(|_| Err(anyhow::anyhow!("Mail reader failed")))
            })
            .collect()
    });
    let fields = fields.into_iter().collect::<Result<Vec<_>>>()?.concat();
    // Headers by one reader, after the fields: if Mail has to fetch a message
    // for them it blocks, so a page sets it fetching one message at most.
    let headers = match read("headers", &ids, left()) {
        Ok(headers) => headers,
        Err(e) if quiet(&e) => vec![],
        Err(e) => return Err(e),
    };
    merge(rows, fields, headers)
        .iter()
        .map(|fields| parse_row(fields, page, zone).ok_or_else(unexpected))
        .collect()
}

/// One page as the AppleScript adapter's `argv`: data only, every text checked
/// at the adapter boundary before US joins a path.
fn page_args<Tz: chrono::TimeZone>(page: &Page, zone: Tz, deadline: Duration) -> Vec<String> {
    let place = |account: &str, nth: usize, path: &[String]| {
        [account.to_owned(), nth.to_string(), path.join("\u{1f}")]
    };
    let [account, nth, path] = match &page.mailbox {
        Some(p) => place(&p.account, p.nth, &p.path),
        None => place("", 0, &[]),
    };
    let [after_account, after_nth, after_path] = match &page.after {
        Some(m) => place(&m.account, m.nth, &m.path),
        None => place("", 0, &[]),
    };
    let before = page
        .before
        .as_deref()
        .and_then(|b| b.parse::<chrono::DateTime<chrono::Utc>>().ok())
        .map(|b| local_text(b, zone))
        .unwrap_or_default();
    vec![
        "messages".into(),
        page.count.to_string(),
        page.scan.to_string(),
        if page.unread_only { "1" } else { "0" }.into(),
        before,
        account,
        nth,
        path,
        after_account,
        after_nth,
        page.after
            .as_ref()
            .map_or(String::new(), |m| m.library_id.to_string()),
        after_path,
        // The adapter gives up after this, to answer in time.
        (deadline.as_secs() * 2 / 3).max(1).to_string(),
    ]
}

/// An instant as "year month day seconds" of local time, rounded up to a whole
/// second: the adapter compares Mail's whole-second, zoneless dates with it.
fn local_text<Tz: chrono::TimeZone>(at: chrono::DateTime<chrono::Utc>, zone: Tz) -> String {
    use chrono::{Datelike, Timelike};
    let mut at = at;
    if at.timestamp_subsec_nanos() > 0 {
        at = at.with_nanosecond(0).unwrap_or(at) + chrono::Duration::seconds(1);
    }
    let local = at.with_timezone(&zone).naive_local();
    format!(
        "{} {} {} {}",
        local.year(),
        local.month(),
        local.day(),
        local.num_seconds_from_midnight()
    )
}

/// A local "year month day seconds" from the adapter as an instant. In the
/// hour that repeats when clocks go back, the earlier one.
fn local_instant<Tz: chrono::TimeZone>(
    text: &str,
    zone: &Tz,
) -> Option<chrono::DateTime<chrono::Utc>> {
    let n: Vec<i64> = text
        .split(' ')
        .map(str::parse)
        .collect::<Result<_, _>>()
        .ok()?;
    let [y, m, d, t] = n[..] else { return None };
    let naive = chrono::NaiveDate::from_ymd_opt(
        y.try_into().ok()?,
        m.try_into().ok()?,
        d.try_into().ok()?,
    )?
    .and_hms_opt(0, 0, 0)?
    .checked_add_signed(chrono::Duration::try_seconds(t).filter(|_| (0..86_400).contains(&t))?)?;
    // A time skipped when clocks went forward reads as the hour after.
    [naive, naive + chrono::Duration::hours(1)]
        .into_iter()
        .find_map(|n| zone.from_local_datetime(&n).earliest())
        .map(|at| at.with_timezone(&chrono::Utc))
}

const US: char = '\u{1f}';
const RS: char = '\u{1e}';
const GS: char = '\u{1d}';
/// A row from `messages`: ID, date, read, flagged, subject, sender, account
/// ID, account name, mailbox name, mailbox path, mailbox nth.
const PAGE_FIELDS: usize = 11;
/// A row from `rows` reading headers: ID, Message-ID, To names, To addresses
/// and whether those are missing ("1").
const HEADER_FIELDS: usize = 5;
/// A message's fields, then its headers.
const ROW_FIELDS: usize = PAGE_FIELDS + HEADER_FIELDS - 1;
/// How many messages one `rows` reader takes, and at most how many readers.
const PER_READER: usize = 6;
const MAX_READERS: usize = 8;

fn readers(messages: usize) -> usize {
    messages.div_ceil(PER_READER).clamp(1, MAX_READERS)
}

/// The mailbox `rows` reads a page's messages from.
#[derive(Debug, PartialEq)]
struct Plan {
    /// "" for the unified inbox.
    account: String,
    /// Its place in the account's mailbox list, and its name, to check.
    index: String,
    name: String,
}

/// The `rows` request for some of a page's messages.
fn rows_args(plan: &Plan, what: &str, ids: &[&str], deadline: Duration) -> Vec<String> {
    vec![
        "rows".into(),
        plan.account.clone(),
        plan.index.clone(),
        plan.name.clone(),
        what.into(),
        // It stops asking for headers after this, to answer in time.
        (deadline.as_secs() * 2 / 3).max(1).to_string(),
        ids.join("\u{1f}"),
    ]
}

/// Records and fields of an answer; an "err" answer as its `Failure`. Any
/// other shape is rejected whole, never guessed at.
fn records(out: &str, deadline: Duration) -> Result<(Vec<String>, Vec<Vec<String>>)> {
    let out = out.strip_suffix('\n').unwrap_or(out);
    let mut records = out
        .split(RS)
        .map(|r| r.split(US).map(str::to_owned).collect::<Vec<_>>());
    let head = records.next().unwrap_or_default();
    match head.first().map(String::as_str) {
        Some("ok") => Ok((head, records.collect())),
        Some("err") if head.len() == 3 => {
            let number = head[1].parse().unwrap_or_default();
            Err(
                match failure(number, text(&head[2]).flatten().unwrap_or_default()) {
                    Failure::TimedOut(_) => Failure::TimedOut(deadline),
                    other => other,
                }
                .into(),
            )
        }
        _ => Err(unexpected()),
    }
}
fn unexpected() -> anyhow::Error {
    anyhow::anyhow!("Mail gave an unexpected answer")
}

/// `messages`' answer: the plan (none for an empty page) and its rows.
fn parse_plan(out: &str, deadline: Duration) -> Result<(Option<Plan>, Vec<Vec<String>>)> {
    let (head, rows) = records(out, deadline)?;
    if rows
        .iter()
        .any(|r| r.len() != PAGE_FIELDS || r[0].parse::<i64>().is_err())
    {
        return Err(unexpected());
    }
    match (&head[1..], rows.is_empty()) {
        ([], true) => Ok((None, rows)),
        ([account, index, name], false) => Ok((
            Some(Plan {
                account: account.clone(),
                index: index.clone(),
                name: name.clone(),
            }),
            rows,
        )),
        _ => Err(unexpected()),
    }
}

/// `rows`' answer, reading "fields" or "headers".
fn parse_rows(out: &str, what: &str, deadline: Duration) -> Result<Vec<Vec<String>>> {
    let (head, rows) = records(out, deadline)?;
    let width = if what == "fields" {
        PAGE_FIELDS
    } else {
        HEADER_FIELDS
    };
    if head.len() != 1 || rows.iter().any(|r| r.len() != width) {
        return Err(unexpected());
    }
    Ok(rows)
}
/// A headers reader that failed this way leaves the page's headers
/// incomplete; Mail not running or not allowed still fails the page.
fn quiet(e: &anyhow::Error) -> bool {
    matches!(
        e.downcast_ref::<Failure>(),
        None | Some(Failure::TimedOut(_) | Failure::Missing | Failure::Other(_))
    )
}

/// The page's rows completed by the readers': each message's fields where
/// the page had none (a large page's subject, the unified inbox's mailbox),
/// then its headers, marked missing where the headers reader didn't get to
/// them. A message the fields readers no longer found is gone: left out.
fn merge(
    rows: Vec<Vec<String>>,
    fields: Vec<Vec<String>>,
    headers: Vec<Vec<String>>,
) -> Vec<Vec<String>> {
    let mut fields: std::collections::HashMap<_, _> =
        fields.into_iter().map(|r| (r[0].clone(), r)).collect();
    let mut headers: std::collections::HashMap<_, _> =
        headers.into_iter().map(|r| (r[0].clone(), r)).collect();
    rows.into_iter()
        .filter_map(|mut row| {
            let read = fields.remove(&row[0])?;
            for i in 1..PAGE_FIELDS {
                if !read[i].is_empty() {
                    row[i].clone_from(&read[i]);
                }
            }
            match headers.remove(&row[0]) {
                Some(head) => row.extend_from_slice(&head[1..]),
                None => row.extend(["", "", "", "1"].map(String::from)),
            }
            Some(row)
        })
        .collect()
}

/// A text field: `Some(None)` for none, `None` when it isn't one.
fn text(field: &str) -> Option<Option<&str>> {
    if field.is_empty() {
        return Some(None);
    }
    field.strip_prefix('+').map(Some)
}
/// A list field: `Some(None)` for none.
fn list(field: &str) -> Option<Option<Vec<Option<String>>>> {
    if field.is_empty() {
        return Some(None);
    }
    let mut parts = field.split(GS);
    let n: usize = parts.next()?.parse().ok()?;
    let items = parts
        .map(|p| text(p).map(|t| t.map(str::to_owned)))
        .collect::<Option<Vec<_>>>()?;
    (items.len() == n).then_some(Some(items))
}
fn parse_row<Tz: chrono::TimeZone>(f: &[String], page: &Page, zone: &Tz) -> Option<Summary> {
    if f.len() != ROW_FIELDS {
        return None;
    }
    let flag = |s: &str| match s {
        "1" => Some(true),
        "0" => Some(false),
        _ => None,
    };
    let owned = |s: &str| text(s).map(|t| t.map(str::to_owned));
    let names = list(&f[12])?.unwrap_or_default();
    let addresses = list(&f[13])?.unwrap_or_default();
    let to = addresses
        .into_iter()
        .enumerate()
        .map(|(i, address)| Person {
            name: names.get(i).cloned().flatten(),
            address,
        })
        .collect();
    let (account_id, mailbox, mailbox_path, mailbox_nth) = match &page.mailbox {
        Some(p) => (
            p.account.clone(),
            p.path.last()?.clone(),
            p.path.clone(),
            p.nth,
        ),
        None => (
            owned(&f[6])??,
            owned(&f[8])??,
            list(&f[9])??.into_iter().collect::<Option<Vec<_>>>()?,
            f[10].parse().ok()?,
        ),
    };
    Some(Summary {
        library_id: f[0].parse().ok()?,
        account_id,
        account: owned(&f[7])?,
        mailbox,
        mailbox_path,
        mailbox_nth,
        subject: owned(&f[4])?,
        sender: owned(&f[5])?,
        to,
        date: if f[1].is_empty() {
            None
        } else {
            Some(local_instant(&f[1], zone)?)
        },
        read: flag(&f[2])?,
        flagged: flag(&f[3])?,
        message_id: owned(&f[11])?,
        incomplete: flag(&f[14])?,
    })
}

/// Runs `osascript` with `args`, killing it at `deadline`; its output.
fn osascript(args: &[&str], input: Option<&[u8]>, deadline: Duration) -> Result<Vec<u8>> {
    use std::io::{Read, Write};
    use std::process::{Command, Stdio};
    crate::bundled("Mail")?;
    let until = std::time::Instant::now()
        .checked_add(deadline)
        .context("Mail reader deadline out of range")?;
    // No shell, no interpolation: the source is fixed, the data are arguments
    // or input.
    let mut child = Command::new("/usr/bin/osascript")
        .env_clear()
        .envs(
            ["HOME", "TMPDIR", "LANG", "LC_ALL", "USER", "LOGNAME"]
                .into_iter()
                .filter_map(|name| std::env::var_os(name).map(|v| (name, v))),
        )
        .args(args)
        .stdin(if input.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        })
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .context("Couldn't start the Mail reader")?;
    if let Some(input) = input {
        child
            .stdin
            .take()
            .context("Mail reader input unavailable")?
            .write_all(input)?;
    }
    let mut stdout = child
        .stdout
        .take()
        .context("Mail reader output unavailable")?;
    let reader = std::thread::spawn(move || {
        let mut out = vec![];
        let _ = (&mut stdout).take(MAX_OUTPUT).read_to_end(&mut out);
        out
    });
    loop {
        if child.try_wait()?.is_some() {
            break;
        }
        if std::time::Instant::now() >= until {
            let _ = child.kill();
            let _ = child.wait();
            return Err(Failure::TimedOut(deadline).into());
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    Ok(reader.join().unwrap_or_default())
}

/// Runs one JXA adapter operation, its input JSON on stdin.
fn run<T: serde::de::DeserializeOwned>(
    operation: &str,
    mut input: serde_json::Value,
    deadline: Duration,
) -> Result<T> {
    debug_assert!(OPERATIONS.contains(&operation));
    input["operation"] = operation.into();
    let out = osascript(
        &["-l", "JavaScript", "-e", ADAPTER],
        Some(input.to_string().as_bytes()),
        deadline,
    )?;
    let reply: serde_json::Value =
        serde_json::from_slice(&out).context("Mail reader gave no answer")?;
    if reply["ok"] != true {
        let number = reply["number"].as_i64().unwrap_or_default();
        return Err(
            match failure(number, reply["error"].as_str().unwrap_or_default()) {
                Failure::TimedOut(_) => Failure::TimedOut(deadline),
                other => other,
            }
            .into(),
        );
    }
    serde_json::from_value(reply["value"].clone()).context("Mail gave an unexpected answer")
}

mod consent {
    //! `AEDeterminePermissionToAutomateTarget` (CoreServices, macOS 10.14+).
    use super::Automation;
    use anyhow::{Result, bail};
    use std::ffi::c_void;

    #[repr(C)]
    struct AEDesc {
        descriptor_type: u32,
        data_handle: *mut c_void,
    }
    #[link(name = "CoreServices", kind = "framework")]
    unsafe extern "C" {
        fn AECreateDesc(kind: u32, data: *const c_void, size: isize, result: *mut AEDesc) -> i16;
        fn AEDisposeDesc(desc: *mut AEDesc) -> i16;
        fn AEDeterminePermissionToAutomateTarget(
            target: *const AEDesc,
            class: u32,
            id: u32,
            ask: u8,
        ) -> i32;
    }
    const fn code(s: &[u8; 4]) -> u32 {
        u32::from_be_bytes(*s)
    }

    /// What macOS has decided about the host sending `core/getd` (get a property)
    /// to the app with `bundle`. Never launches it. With `ask`, shows the
    /// system prompt if nothing was decided, and waits for the answer.
    pub fn determine(bundle: &str, ask: bool) -> Result<Automation> {
        let mut target = AEDesc {
            descriptor_type: 0,
            data_handle: std::ptr::null_mut(),
        };
        // SAFETY: AECreateDesc copies `bundle`'s bytes into a new descriptor,
        // which is disposed of below.
        let made = unsafe {
            AECreateDesc(
                code(b"bund"),
                bundle.as_ptr().cast(),
                bundle.len() as isize,
                &mut target,
            )
        };
        if made != 0 {
            bail!("Couldn't address Mail (error {made})");
        }
        // SAFETY: `target` is a valid descriptor until disposed of.
        let status = unsafe {
            let status = AEDeterminePermissionToAutomateTarget(
                &target,
                code(b"core"),
                code(b"getd"),
                ask as u8,
            );
            AEDisposeDesc(&mut target);
            status
        };
        Ok(match status {
            0 => Automation::Granted,
            -1744 => Automation::NotDetermined,
            -1743 => Automation::Denied,
            -600 => Automation::NotRunning,
            other => bail!("macOS couldn't tell whether the app may read Mail (error {other})"),
        })
    }
}

#[cfg(test)]
#[path = "tests.rs"]
mod tests;
