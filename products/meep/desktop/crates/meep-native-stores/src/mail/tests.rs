use super::*;

#[test]
fn apple_event_errors_read_in_plain_words() {
    assert_eq!(failure(-600, ""), Failure::NotRunning);
    assert_eq!(failure(-609, "Connection is invalid."), Failure::NotRunning);
    assert_eq!(failure(-1743, "Not authorized"), Failure::Denied);
    assert_eq!(failure(-1744, ""), Failure::Denied);
    assert_eq!(failure(-1728, "Can't get object."), Failure::Missing);
    assert!(matches!(failure(-1712, ""), Failure::TimedOut(_)));
    assert_eq!(
        failure(
            -10000,
            "Error: Mail got an error: AppleEvent handler failed."
        ),
        Failure::Other("Mail got an error: AppleEvent handler failed.".into())
    );
    let long = failure(1, &"é".repeat(300)).to_string();
    assert!(long.len() < 260, "{long}");
    for (f, says) in [
        (Failure::NotRunning, "Open the Mail app"),
        (
            Failure::Denied,
            "System Settings → Privacy & Security → Automation",
        ),
        (Failure::TimedOut(Duration::from_secs(30)), "30 seconds"),
    ] {
        assert!(f.to_string().contains(says), "{f}");
    }
}

/// The JXA adapter only reads: its operations are the two reads, and it
/// never sets a property or sends Mail a command.
#[test]
fn the_jxa_adapter_has_only_read_operations() {
    let cases: Vec<&str> = ADAPTER
        .lines()
        .filter_map(|l| l.trim().strip_prefix("case '"))
        .filter_map(|l| l.split('\'').next())
        .collect();
    assert_eq!(cases, OPERATIONS);
    let code: String = ADAPTER
        .lines()
        .filter(|l| !l.trim_start().starts_with("//"))
        .collect::<Vec<_>>()
        .join("\n");
    for forbidden in [
        ".activate",
        ".open(",
        ".delete(",
        ".move(",
        ".duplicate(",
        ".send(",
        ".reply(",
        ".forward(",
        ".redirect(",
        ".bounce(",
        ".save(",
        ".make(",
        "checkForNewMail",
        "synchronize",
        ".source(",
        ".allHeaders(",
        "readStatus =",
        "flaggedStatus =",
        ".set(",
        "eval(",
        "Function(",
        "doShellScript",
        "includeStandardAdditions",
        ".launch(",
    ] {
        assert!(!code.contains(forbidden), "the adapter uses {forbidden}");
    }
    // Mail is addressed only after the running check.
    let check = code
        .find("runningApplicationsWithBundleIdentifier")
        .unwrap();
    let first = code.find("Application('com.apple.mail')").unwrap();
    assert!(check < first);
    assert_eq!(code.matches("Application(").count(), 1);
}

/// The page adapter's code without its comments, and its "Mail" section.
fn page_code() -> (String, String) {
    let code: String = PAGE_ADAPTER
        .lines()
        .filter(|l| !l.trim_start().starts_with("--"))
        .collect::<Vec<_>>()
        .join("\n");
    let cut = PAGE_ADAPTER.find("-- Mail ---").unwrap();
    let mail: String = PAGE_ADAPTER[cut..]
        .lines()
        .filter(|l| !l.trim_start().starts_with("--"))
        .collect::<Vec<_>>()
        .join("\n");
    (code, mail)
}

/// The read-only Mail.sdef terms the page adapter may use, as raw codes:
/// classes to address, and properties that only read.
const PAGE_TERMS: &[&str] = &[
    "«class mssg»",    // message
    "«class mbxp»",    // mailbox
    "«class mbxc»",    // container
    "«class mact»",    // account
    "«class trcp»",    // to recipient
    "«property inmb»", // inbox
    "«property mbxc»", // container (of a mailbox)
    "«property mact»", // account (of a mailbox)
    "«property mbxp»", // mailbox (of a message)
    "«property mbuc»", // unread count
    "«property rdrc»", // date received
    "«property isrd»", // read status
    "«property isfl»", // flagged status
    "«property subj»", // subject
    "«property sndr»", // sender
    "«property meid»", // message id
    "«property radd»", // address (of a recipient record)
    "«property pALL»", // properties: of recipients only, checked below
];

/// The page adapter only reads. Its operations are the two reads; only its
/// "Mail" section talks to Mail, through one variable set after the running
/// check; it names Mail's terms only from `PAGE_TERMS`, sets nothing but its
/// own variables, and has no command that changes, opens or launches.
#[test]
fn the_page_adapter_has_only_read_operations() {
    let (code, mail) = page_code();
    assert!(code.contains("if op is not \"messages\" then error"));
    assert!(code.contains("item 1 of argv is \"rows\" then return rowsOf(argv)"));
    let logic = &code[..code.find("global mailApp").unwrap()];
    for outside in ["tell ", "«", "application", "mailApp"] {
        assert!(
            !logic.contains(outside),
            "{outside} outside the Mail section"
        );
    }
    let mut terms = mail.match_indices('«').map(|(at, _)| {
        let end = mail[at..].find('»').unwrap() + at;
        &mail[at..end + '»'.len_utf8()]
    });
    assert!(terms.all(|t| PAGE_TERMS.contains(&t)), "{mail}");
    // `properties` would read a message's content and source: recipients only.
    assert_eq!(
        mail.matches("«property pALL»").count(),
        mail.matches("«property pALL» of every «class trcp» of r")
            .count()
    );
    // `set` only names the adapter's own variables: in the Mail section
    // bare names, and every one a variable, not a term AppleScript knows
    // (`kind` would be one, and `set kind to` an Apple event).
    let mut names = std::collections::BTreeSet::new();
    for (at, _) in code.match_indices("set ") {
        if at > 0
            && code[..at]
                .chars()
                .last()
                .is_some_and(|c| c.is_alphanumeric())
        {
            continue;
        }
        let target = code[at + 4..].split(" to ").next().unwrap();
        let target = target.lines().next().unwrap();
        let bare = target
            .trim_start_matches("end of ")
            .trim_matches(|c| c == '{' || c == '}')
            .split(", ")
            .all(|w| w.chars().all(|c| c.is_ascii_alphanumeric()));
        if mail.contains(&format!("set {target} to")) {
            assert!(bare, "the Mail section sets {target}");
        }
        if bare && !target.starts_with("end of ") {
            names.extend(
                target
                    .trim_matches(|c| c == '{' || c == '}')
                    .split(", ")
                    .map(str::to_owned),
            );
        }
    }
    let probe: String = names
        .iter()
        .map(|n| format!("try\n\tset {n} to 1\non error\n\tset end of terms to \"{n}\"\nend try\n"))
        .collect();
    let probe = format!("set terms to {{}}\n{probe}return terms as text");
    let terms = std::process::Command::new("/usr/bin/osascript")
        .args(["-e", &probe])
        .env_clear()
        .output()
        .unwrap();
    assert!(terms.status.success() && names.len() > 20, "{names:?}");
    assert_eq!(
        String::from_utf8_lossy(&terms.stdout).trim(),
        "",
        "set targets that are terms"
    );
    let words = |text: &str| -> Vec<String> {
        text.split(|c: char| !c.is_alphanumeric())
            .map(str::to_lowercase)
            .collect()
    };
    let all = words(&code);
    for forbidden in [
        "delete",
        "move",
        "duplicate",
        "make",
        "save",
        "close",
        "open",
        "activate",
        "launch",
        "reopen",
        "quit",
        "send",
        "reply",
        "forward",
        "redirect",
        "bounce",
        "synchronize",
        "copy",
        "shell",
        "content",
        "source",
        "headers",
        "event",
        "data",
        "attribute",
        "load",
        "store",
        "run",
        "ctnt",
        "raso",
        "alhe",
    ] {
        let allowed = match forbidden {
            // "on run argv", "headerFields", "messageHeaders" and their comments.
            "run" => code.matches("on run argv").count() + code.matches("end run").count(),
            "headers" => 0,
            _ => 0,
        };
        assert_eq!(
            all.iter().filter(|w| *w == forbidden).count(),
            allowed,
            "the page adapter uses {forbidden}"
        );
    }
    // Mail is addressed only after the running check, by bundle ID.
    let check = mail
        .find("if not (application id \"com.apple.mail\" is running) then error")
        .unwrap();
    let first = mail
        .find("set mailApp to application id \"com.apple.mail\"")
        .unwrap();
    assert!(check < first);
    assert_eq!(code.matches("application").count(), 2);
    // Compiled, the terms are still only those: no word read as a term.
    let decompiled = decompile(PAGE_ADAPTER);
    for (at, _) in decompiled.match_indices('«') {
        let end = decompiled[at..].find('»').unwrap() + at;
        let term = &decompiled[at..end + '»'.len_utf8()];
        let same = PAGE_TERMS
            .iter()
            .any(|t| t[t.len() - 5 - '»'.len_utf8()..] == term[term.len() - 5 - '»'.len_utf8()..]);
        assert!(same, "compiles to {term}");
    }
}

/// Compiles AppleScript (no Apple event: Mail is addressed through a
/// variable, so no dictionary is loaded) and gives it back as text.
fn decompile(source: &str) -> String {
    let dir = tempfile::tempdir().expect("mail adapter fixture directory");
    let compiled = dir.path().join("page.scpt");
    let output = std::process::Command::new("/usr/bin/osacompile")
        .arg("-o")
        .arg(&compiled)
        .arg("-e")
        .arg(source)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = std::process::Command::new("/usr/bin/osadecompile")
        .arg(&compiled)
        .output()
        .unwrap();
    let text = String::from_utf8_lossy(&text.stdout).into_owned();
    assert!(text.contains("on page(argv)"), "{text}");
    text
}

/// Runs the real JXA adapter's logic in JavaScriptCore's `jsc` shell,
/// against a fake of Mail's object model loaded before it (tests/fixtures/
/// mail-fake.js). `jsc` has no scripting bridge, so no Apple event can be
/// sent; the adapter itself is unchanged. Real Mail semantics (specifier
/// behaviour, whether reading `content` marks a message read) stay
/// unverified here.
#[test]
fn the_jxa_adapter_reads_a_fake_mail() {
    const JSC: &str =
        "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc";
    let dir = tempfile::tempdir().expect("mail adapter fixture directory");
    let script = dir.path().join("checks.js");
    std::fs::write(
        &script,
        [
            include_str!("../../tests/fixtures/mail-fake.js"),
            ADAPTER,
            include_str!("../../tests/fixtures/mail-adapter-checks.js"),
        ]
        .join("\n"),
    )
    .unwrap();
    let output = std::process::Command::new(JSC)
        .arg(&script)
        .output()
        .unwrap();
    let printed = String::from_utf8_lossy(&output.stdout).into_owned()
        + String::from_utf8_lossy(&output.stderr).as_ref();
    assert!(
        output.status.success() && printed.trim_end().ends_with("all passed"),
        "{printed}"
    );
}

/// The page adapter's own code with tests/fixtures/mail-fake.applescript
/// in place of its "Mail" section: it addresses no application, so no
/// Apple event is sent. Its run handler adds FS and how many Mail events
/// the call stood for.
fn harness() -> String {
    let cut = PAGE_ADAPTER.find("-- Mail ---").unwrap();
    let fake = include_str!("../../tests/fixtures/mail-fake.applescript");
    let code = fake.lines().filter(|l| !l.trim_start().starts_with("--"));
    assert!(
        code.clone()
            .all(|l| !l.contains("application") && !l.contains("tell "))
    );
    PAGE_ADAPTER[..cut].replacen("on run argv", "on adapterRun(argv)", 1)
        + fake
        + "\non run argv\n\tset answer to adapterRun(argv)\n\treturn answer & (character id 28) & fakeEvents\nend run\n"
}

/// `read_page` against the fake Mail named `kind`: the page, and the Mail
/// events each adapter run stood for.
fn fake_page(kind: &str, page: &Page) -> (Result<Vec<Summary>>, Vec<usize>) {
    let source = harness();
    let events = Mutex::new(vec![]);
    let found = read_page(page, Duration::from_secs(60), &chrono::Local, |argv, _| {
        let out = std::process::Command::new("/usr/bin/osascript")
            .arg("-e")
            .arg(&source)
            .args(argv)
            .env_clear()
            .env("MEEP_MAIL_FAKE", kind)
            .output()?;
        let out = String::from_utf8(out.stdout)?;
        let (answer, count) = out.trim_end_matches('\n').rsplit_once('\u{1c}').unwrap();
        events.lock().unwrap().push(count.parse().unwrap());
        Ok(answer.to_owned())
    });
    (found, events.into_inner().unwrap())
}
use std::sync::Mutex;

fn place(account: &str, path: &[&str], nth: usize) -> Place {
    Place {
        account: account.into(),
        path: path.iter().map(|n| n.to_string()).collect(),
        nth,
    }
}
fn first_page(mailbox: Option<Place>, count: usize) -> Page {
    Page {
        mailbox,
        count,
        scan: count,
        before: None,
        after: None,
        unread_only: false,
    }
}
/// What the host keeps of an answer: newest first by date, then ID, the
/// first `count`.
fn kept(mut found: Vec<Summary>, count: usize) -> Vec<Summary> {
    found.sort_by_key(|s| std::cmp::Reverse((s.date, s.library_id)));
    found.truncate(count);
    found
}
/// `pages` pages of `count`, each after the last message of the one before.
fn walk(kind: &str, mailbox: Place, count: usize, pages: usize) -> (Vec<i64>, Vec<usize>) {
    let (mut ids, mut events, mut page) =
        (vec![], vec![], first_page(Some(mailbox.clone()), count));
    for _ in 0..pages {
        let (found, spent) = fake_page(kind, &page);
        let found = kept(found.unwrap(), count);
        events.push(spent.iter().sum());
        let Some(last) = found.last() else { break };
        ids.extend(found.iter().map(|s| s.library_id));
        page.after = Some(MessageRef {
            account: mailbox.account.clone(),
            path: mailbox.path.clone(),
            nth: mailbox.nth,
            library_id: last.library_id,
        });
    }
    (ids, events)
}

#[test]
#[ignore = "runs the Mail script through osascript (~40 s); run with --ignored after changing it"]
fn the_page_adapter_pages_a_fake_mail_exactly() {
    // Newest first, three to a second, IDs rising with age inside a second.
    let want: Vec<i64> = (0..)
        .flat_map(|s: i64| (0..3).rev().map(move |j| 1_000_000 + s * 3 + j))
        .take(250)
        .collect();
    let inbox = place("ACC-1", &["INBOX"], 0);
    let (ids, events) = walk("big", inbox.clone(), 50, 5);
    assert_eq!(
        ids, want,
        "pages lose or repeat nothing across shared seconds"
    );
    // Mail events: the page's own fields (7 a message) and a constant
    // few, not one per message of the mailbox or per halving.
    assert!(events.iter().all(|&e| e <= 7 * 51 + 40), "{events:?}");
    let (old, _) = walk("big", place("ACC-1", &["Old"], 0), 50, 5);
    assert_eq!(old, want, "oldest-first mailboxes page newest first");
    let (burst, _) = walk("big", place("ACC-1", &["Burst"], 0), 50, 10);
    assert_eq!(
        burst.len(),
        300,
        "a second larger than a page pages without loss"
    );
    assert_eq!(
        burst.iter().collect::<std::collections::HashSet<_>>().len(),
        300
    );
    let (empty, _) = walk("big", place("ACC-1", &["Empty"], 0), 20, 1);
    assert!(empty.is_empty());
    let (one, _) = walk("big", place("ACC-1", &["One"], 0), 20, 2);
    assert_eq!(one, [4_000_000]);

    // A plain date takes only older messages.
    let cut = kept(
        fake_page("big", &first_page(Some(inbox.clone()), 3))
            .0
            .unwrap(),
        3,
    )[2]
    .date
    .unwrap();
    let mut dated = first_page(Some(inbox.clone()), 5);
    dated.before = Some(cut.to_rfc3339_opts(chrono::SecondsFormat::Millis, true));
    let older = fake_page("big", &dated).0.unwrap();
    assert!(older.len() >= 5 && older.iter().all(|m| m.date.unwrap() < cut));

    // Unread only: every 7th of 1000 is unread.
    let mut unread = first_page(Some(place("ACC-1", &["Unread"], 0)), 5);
    (unread.scan, unread.unread_only) = (200, true);
    let found = kept(
        fake_page("big", &unread)
            .0
            .unwrap()
            .into_iter()
            .filter(|m| !m.read)
            .collect(),
        5,
    );
    assert_eq!(
        found.iter().map(|m| m.library_id).collect::<Vec<_>>(),
        [3_000_000, 3_000_007, 3_000_014, 3_000_021, 3_000_028]
    );

    // Every field of a message, as the host gets it.
    let m = &kept(
        fake_page("big", &first_page(Some(inbox.clone()), 1))
            .0
            .unwrap(),
        1,
    )[0];
    assert_eq!(m.library_id, 1_000_002);
    assert_eq!(
        (
            m.account_id.as_str(),
            m.account.as_deref(),
            m.mailbox.as_str(),
            m.mailbox_path.as_slice()
        ),
        (
            "ACC-1",
            Some("iCloud"),
            "INBOX",
            ["INBOX".to_string()].as_slice()
        )
    );
    assert_eq!(m.subject.as_deref(), Some("Subject 1000002"));
    assert_eq!(m.sender.as_deref(), Some("Ada <ada@example.com>"));
    assert_eq!(m.message_id.as_deref(), Some("m1000002@example.com"));
    assert_eq!(
        m.to.iter()
            .map(|p| (p.name.as_deref(), p.address.as_deref()))
            .collect::<Vec<_>>(),
        [
            (Some("Me"), Some("me@example.com")),
            (None, Some("you@example.com"))
        ]
    );
    assert!(m.read && !m.flagged && !m.incomplete);
    let local = chrono::Local
        .with_ymd_and_hms(2026, 11, 1, 9, 0, 0)
        .unwrap()
        .with_timezone(&chrono::Utc);
    assert_eq!(m.date, Some(local));

    // Mail not running: refused before anything is read.
    let (off, events) = fake_page("off", &first_page(None, 5));
    assert_eq!(
        off.unwrap_err().downcast_ref::<Failure>(),
        Some(&Failure::NotRunning)
    );
    assert_eq!(events, [0]);
}
use chrono::TimeZone as _;

#[test]
fn the_page_adapter_finds_nested_mailboxes_and_the_unified_inbox() {
    let ids = |kind, mailbox: Place, count| -> Vec<i64> {
        kept(
            fake_page(kind, &first_page(Some(mailbox), count))
                .0
                .unwrap(),
            count,
        )
        .iter()
        .map(|m| m.library_id)
        .collect()
    };
    assert_eq!(
        ids("nested", place("ACC-2", &["Github", "Alerts"], 0), 50),
        (8500..8506).collect::<Vec<_>>()
    );
    assert_eq!(ids("nested", place("ACC-1", &["Alerts"], 0), 50), [9100]);
    let (sent, _) = walk(
        "nested",
        place("ACC-2", &["[Gmail]", "Sent Mail"], 0),
        25,
        4,
    );
    assert_eq!(sent, (8300..8360).collect::<Vec<_>>());
    // Two mailboxes Mail names no container for: each by its place among them.
    assert_eq!(
        ids("nested", place("ACC-3", &["Alerts"], 0), 50),
        [9600, 9601]
    );
    assert_eq!(
        ids("nested", place("ACC-3", &["Alerts"], 1), 50),
        [9700, 9701, 9702]
    );
    for missing in [
        place("ACC-3", &["Alerts"], 2),
        place("ACC-2", &["Sent Mail"], 0),
        place("ACC-2", &["Nope", "Sent Mail"], 0),
    ] {
        let error = fake_page("nested", &first_page(Some(missing), 5))
            .0
            .unwrap_err();
        assert_eq!(error.downcast_ref::<Failure>(), Some(&Failure::Missing));
    }
    // The unified inbox: each message names its own mailbox.
    let unified = fake_page("nested", &first_page(None, 5)).0.unwrap();
    assert_eq!(unified.len(), 2);
    assert!(unified.iter().all(|m| m.account_id == "ACC-1"
        && m.account.as_deref() == Some("iCloud")
        && m.mailbox == "INBOX"
        && m.mailbox_path == ["INBOX"]));
}

/// Mail can't give a message's headers in time: that message and the rest
/// come back incomplete, with every other field, rather than not at all.
#[test]
fn a_page_answers_without_headers_mail_hasnt_downloaded() {
    let found = kept(
        fake_page(
            "stall",
            &first_page(Some(place("ACC-1", &["INBOX"], 0)), 20),
        )
        .0
        .unwrap(),
        20,
    );
    assert_eq!(found.len(), 20);
    for (age, m) in found.iter().enumerate() {
        assert_eq!(m.incomplete, age >= 5, "{age}");
        assert_eq!(m.message_id.is_none(), age >= 5);
        assert_eq!(
            m.subject.as_deref(),
            Some(format!("Subject {}", 1000 + age).as_str())
        );
    }
}

/// Texts holding the answer's separators, quotes, line breaks, emoji and
/// 5000 characters can't add a field or a message.
#[test]
fn hostile_text_stays_in_its_field() {
    let found = kept(
        fake_page(
            "hostile",
            &first_page(Some(place("ACC-1", &["INBOX"], 0)), 5),
        )
        .0
        .unwrap(),
        5,
    );
    assert_eq!(found.len(), 3);
    assert_eq!(
        found[0].subject.as_deref(),
        Some("a    b \"quoted\" \rline\nend +")
    );
    assert_eq!(found[1].subject.as_deref(), Some("Café 🎉 ✓ 中文     "));
    assert_eq!(found[2].subject.as_deref().map(str::len), Some(5000));
    assert_eq!(found[0].message_id, found[0].subject);
    assert_eq!(found[0].to[0].name, found[0].subject);
    assert_eq!(found[0].to[1].address.as_deref(), Some("you@example.com"));
    assert!(found.iter().all(|m| !m.incomplete && m.mailbox == "INBOX"));
}

#[test]
fn answers_of_any_other_shape_are_rejected_whole() {
    let page = first_page(Some(place("ACC-1", &["INBOX"], 0)), 5);
    let row = "7\u{1f}2026 11 1 32400\u{1f}1\u{1f}0\u{1f}+Hi\u{1f}+Ada\u{1f}+ACC-1\u{1f}+iCloud\u{1f}\u{1f}\u{1f}0";
    let (plan, rows) = parse_plan(
        &format!("ok\u{1f}ACC-1\u{1f}3\u{1f}INBOX\u{1e}{row}\n"),
        Duration::ZERO,
    )
    .unwrap();
    assert_eq!(plan.unwrap().index, "3");
    assert_eq!(rows.len(), 1);
    for bad in [
        "",
        "nonsense",
        "ok\u{1f}ACC-1\u{1f}3",
        // A message with a field too many or too few.
        &format!("ok\u{1f}ACC-1\u{1f}3\u{1f}INBOX\u{1e}{row}\u{1f}x"),
        "ok\u{1f}ACC-1\u{1f}3\u{1f}INBOX\u{1e}7\u{1f}x",
        // A text not marked as one.
        &format!(
            "ok\u{1f}ACC-1\u{1f}3\u{1f}INBOX\u{1e}{}",
            row.replace("+Hi", "Hi")
        ),
    ] {
        let parsed = parse_plan(bad, Duration::ZERO).and_then(|(_, rows)| {
            let fields = merge(rows.clone(), rows, vec![]);
            fields
                .iter()
                .map(|f| parse_row(f, &page, &chrono::Utc).ok_or_else(unexpected))
                .collect::<Result<Vec<_>>>()
        });
        assert!(parsed.is_err(), "{bad:?}");
    }
    assert!(parse_rows("ok\u{1e}7\u{1f}+m\u{1f}0\u{1f}0", "headers", Duration::ZERO).is_err());
    assert!(
        parse_rows(
            "ok\u{1e}7\u{1f}+m\u{1f}0\u{1f}0\u{1f}0",
            "headers",
            Duration::ZERO
        )
        .is_ok()
    );
    // A list whose count doesn't match its items.
    assert_eq!(list("2\u{1d}+a"), None);
    assert_eq!(
        list("2\u{1d}+a\u{1d}"),
        Some(Some(vec![Some("a".into()), None]))
    );
    assert_eq!(list(""), Some(None));
    // Errors read as Mail's.
    let error = parse_plan("err\u{1f}-600\u{1f}+Mail is not running", Duration::ZERO).unwrap_err();
    assert_eq!(error.downcast_ref::<Failure>(), Some(&Failure::NotRunning));
    let error = parse_plan("err\u{1f}-1712\u{1f}+slow", Duration::from_secs(30)).unwrap_err();
    assert_eq!(
        error.downcast_ref::<Failure>(),
        Some(&Failure::TimedOut(Duration::from_secs(30)))
    );
}

/// Mail's dates are local and zoneless: an instant goes out as local time,
/// rounded up to a second, and comes back as the instant it was, on
/// either side of a clock change.
#[test]
fn local_dates_cross_clock_changes() {
    let london = chrono_tz::Europe::London;
    let at = |s: &str| s.parse::<chrono::DateTime<chrono::Utc>>().unwrap();
    assert_eq!(
        local_text(at("2026-07-01T11:00:00Z"), london),
        "2026 7 1 43200"
    );
    assert_eq!(
        local_text(at("2026-07-01T11:00:00.001Z"), london),
        "2026 7 1 43201"
    );
    assert_eq!(
        local_text(at("2026-01-01T11:00:00Z"), london),
        "2026 1 1 39600"
    );
    for instant in [
        "2026-03-29T00:59:59Z",
        "2026-03-29T01:00:00Z",
        "2026-10-25T00:30:00Z",
    ] {
        let text = local_text(at(instant), london);
        assert_eq!(local_instant(&text, &london), Some(at(instant)), "{text}");
    }
    // The repeated hour reads as the earlier; the skipped one as the hour after.
    assert_eq!(
        local_instant("2026 10 25 5400", &london),
        Some(at("2026-10-25T00:30:00Z"))
    );
    assert_eq!(
        local_instant("2026 3 29 3600", &london),
        Some(at("2026-03-29T01:00:00Z"))
    );
    for bad in ["", "2026 13 1 0", "2026 1 1 86400", "2026 1 1", "a b c d"] {
        assert_eq!(local_instant(bad, &london), None, "{bad}");
    }
}

/// A page goes to the adapter as arguments, every one data.
#[test]
fn pages_go_to_the_adapter_as_data() {
    let page = Page {
        mailbox: Some(place("ACC-1", &["Work \"stuff\"", "it's -- here"], 2)),
        count: 20,
        scan: 200,
        before: None,
        after: Some(MessageRef {
            account: "ACC-2".into(),
            path: vec!["INBOX".into()],
            nth: 0,
            library_id: 42,
        }),
        unread_only: true,
    };
    assert_eq!(
        page_args(&page, chrono::Utc, Duration::from_secs(30)),
        [
            "messages",
            "20",
            "200",
            "1",
            "",
            "ACC-1",
            "2",
            "Work \"stuff\"\u{1f}it's -- here",
            "ACC-2",
            "0",
            "42",
            "INBOX",
            "20"
        ]
    );
    let plan = Plan {
        account: String::new(),
        index: String::new(),
        name: String::new(),
    };
    assert_eq!(
        rows_args(&plan, "fields", &["1", "2"], Duration::from_secs(9)),
        ["rows", "", "", "", "fields", "6", "1\u{1f}2"]
    );
    assert_eq!(readers(1), 1);
    assert_eq!(readers(7), 2);
    assert_eq!(readers(50), MAX_READERS);
}
