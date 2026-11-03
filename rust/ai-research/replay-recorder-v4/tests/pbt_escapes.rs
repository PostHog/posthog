//! Property tests for the writer on pages that spell URLs in unusual ways: CSS escapes, quotes, comments and copies of
//! a URL outside its slot. They search for bugs rather than guard against them, so CI does not run them: each bug they
//! find gets an example test in `src/write.rs`. Run them with
//! `cargo test -p replay-recorder-v4 --test pbt_escapes -- --ignored`, and set `HEGEL_TEST_CASES` for a longer search.

use hegel::generators as gs;
use hegel::TestCase;
use replay_core_v4::inspect::session::{BlockInspection, SessionInspector};
use replay_core_v4::inspect::stats::BlockStats;
use replay_core_v4::scan::message::read_message;
use replay_recorder_v4::batch::{Block, Origin, SessionKey, Tp};
use replay_recorder_v4::write::{write_block, WriterCounts};
use serde_json::{json, Value};

/// The query value of every refused URL. No other part of a generated page holds it.
const SECRET: &str = "pbtsecret";
/// The host label of every accepted URL. No other part of a generated page holds it.
const ACCEPTED: &str = "pbt-ok";

const HOSTS: &[&str] = &[
    "cdn.example.com",
    "CDN.Example.COM",
    "bucket.s3.amazonaws.com",
];
const REFUSALS: &[&str] = &["?token=", "?X-Amz-Signature=", "?sig="];

#[derive(Debug, Clone, Copy)]
enum Slot {
    ImgSrc,
    Srcset,
    StyleAttribute,
    StyleSheet,
    FontFace(&'static str),
    ImageSet,
    StyleRule,
    StyleChange,
    StyleObjectChange,
}

const SLOTS: &[Slot] = &[
    Slot::ImgSrc,
    Slot::Srcset,
    Slot::StyleAttribute,
    Slot::StyleSheet,
    Slot::FontFace("Brand"),
    Slot::FontFace("Roboto"),
    Slot::ImageSet,
    Slot::StyleRule,
    Slot::StyleChange,
    Slot::StyleObjectChange,
];

impl Slot {
    fn is_css(self) -> bool {
        !matches!(self, Slot::ImgSrc | Slot::Srcset)
    }
}

/// A URL as the page writes it in its slot, and the spellings a copy of it can take elsewhere.
struct Placed {
    slot: Slot,
    written: String,
    escaped: bool,
    copies: Vec<String>,
}

fn draw_index(tc: &TestCase, len: usize) -> usize {
    tc.draw(gs::integers::<usize>().min_value(0).max_value(len - 1))
}

fn draw_url(tc: &TestCase, index: usize, refused: bool) -> String {
    let host = if refused {
        HOSTS[draw_index(tc, HOSTS.len())].to_owned()
    } else {
        format!("{ACCEPTED}-{index}.example.com")
    };
    let path = ["a.png", "img/b.png", "f.woff2"][draw_index(tc, 3)];
    let scheme = ["https://", "//"][draw_index(tc, 2)];
    let query = if refused {
        format!("{}{SECRET}", REFUSALS[draw_index(tc, REFUSALS.len())])
    } else {
        String::new()
    };
    format!("{scheme}{host}/{path}{query}")
}

/// `url` with CSS escapes in the part before its query, so the secret stays readable as plain text.
fn css_escaped(tc: &TestCase, url: &str) -> String {
    let query_at = url.find('?').unwrap_or(url.len());
    let mut out = String::new();
    for (at, ch) in url.char_indices() {
        let escape = at < query_at && tc.draw(gs::integers::<u8>().min_value(0).max_value(5)) == 0;
        if !escape {
            out.push(ch);
            continue;
        }
        match draw_index(tc, 3) {
            1 => out.push_str(&format!("\\{:06X}", ch as u32)),
            2 if !ch.is_ascii_hexdigit() => {
                out.push('\\');
                out.push(ch);
            }
            _ => out.push_str(&format!("\\{:x} ", ch as u32)),
        }
    }
    out
}

/// The CSS `url()` of `written`, quoted or not, under any spelling of its name. A comment can follow a quoted string.
/// One before it makes a bad URL, which a browser never loads.
fn url_function(tc: &TestCase, written: &str) -> String {
    let name = ["url", "URL", "\\75 rl", "u\\72l"][draw_index(tc, 4)];
    let comment = if tc.draw(gs::booleans()) { "/*c*/" } else { "" };
    let space = if tc.draw(gs::booleans()) { " " } else { "" };
    match draw_index(tc, 3) {
        0 if !written.contains([' ', '(', ')', '"', '\'', '\\']) => format!("{name}({written})"),
        1 => format!("{name}({space}\"{written}\"{comment})"),
        _ => format!("{name}({space}'{written}'{comment})"),
    }
}

/// `data` as posthog-js sends a compressed snapshot: gzip bytes, one per character.
fn compressed(data: &Value) -> String {
    replay_core_v4::compression::gzip(data.to_string().as_bytes())
        .unwrap()
        .iter()
        .map(|&byte| char::from(byte))
        .collect()
}

/// `json` with some of its slashes written as `\/`, which JSON reads as a slash. Every slash here is inside a string.
fn with_escaped_slashes(tc: &TestCase, json: &str) -> String {
    json.chars()
        .map(|ch| {
            if ch == '/' && draw_index(tc, 4) == 0 {
                "\\/".to_owned()
            } else {
                ch.to_string()
            }
        })
        .collect()
}

fn draw_placed(tc: &TestCase, index: usize, refused: bool) -> Placed {
    let slot = SLOTS[draw_index(tc, SLOTS.len())];
    let url = draw_url(tc, index, refused);
    let written = if slot.is_css() && tc.draw(gs::booleans()) {
        css_escaped(tc, &url)
    } else {
        url.clone()
    };
    let escaped = written != url;
    let copies = if refused {
        tc.draw(gs::vecs(gs::sampled_from(vec![url, written.clone()])).max_size(2))
    } else {
        Vec::new()
    };
    Placed {
        slot,
        written,
        escaped,
        copies,
    }
}

fn element(id: &mut i64, tag: &str, attributes: Value) -> Value {
    *id += 1;
    json!({"type": 2, "tagName": tag, "attributes": attributes, "childNodes": [], "id": *id})
}

/// A full snapshot with each URL in its slot and each copy in an `alt` attribute or a text node, then a style rule
/// event for each URL whose slot is one.
fn events(tc: &TestCase, placed: &[Placed]) -> String {
    let mut id = 1;
    let mut nodes = Vec::new();
    let mut rules = Vec::new();
    for Placed {
        slot,
        written,
        copies,
        ..
    } in placed
    {
        let function = || url_function(tc, written);
        match slot {
            Slot::ImgSrc => nodes.push(element(&mut id, "img", json!({"src": written}))),
            Slot::Srcset => nodes.push(element(
                &mut id,
                "img",
                json!({"srcset": format!("{written} 1x, https://cdn.example.com/other.png 2x")}),
            )),
            Slot::StyleAttribute => nodes.push(element(
                &mut id,
                "div",
                json!({"style": format!("background-image:{}", function())}),
            )),
            Slot::StyleSheet => nodes.push(element(
                &mut id,
                "style",
                json!({"_cssText": format!(".a{{background:{}}}", function())}),
            )),
            Slot::FontFace(family) => nodes.push(element(
                &mut id,
                "style",
                json!({"_cssText": format!("@font-face{{font-family:{family};src:{}}}", function())}),
            )),
            Slot::ImageSet => nodes.push(element(
                &mut id,
                "div",
                json!({"style": format!("background-image:image-set({} 1x)", function())}),
            )),
            Slot::StyleRule => rules.push(json!({"type": 3, "timestamp": 2, "data": {"source": 8, "id": 3,
                "replaceSync": format!(".r{{background:{}}}", function())}})),
            Slot::StyleChange => {
                nodes.push(element(&mut id, "div", json!({})));
                rules.push(json!({"type": 3, "timestamp": 2, "data": {"source": 0, "adds": [], "removes": [], "texts": [],
                    "attributes": [{"id": id, "attributes": {"style": format!("background-image:{}", function())}}]}}));
            }
            Slot::StyleObjectChange => {
                nodes.push(element(&mut id, "div", json!({})));
                rules.push(json!({"type": 3, "timestamp": 2, "data": {"source": 0, "adds": [], "removes": [], "texts": [],
                    "attributes": [{"id": id, "attributes": {"style": {"background-image": function()}}}]}}));
            }
        }
        for copy in copies {
            if tc.draw(gs::booleans()) {
                nodes.push(element(&mut id, "img", json!({"alt": copy})));
            } else {
                id += 1;
                nodes.push(json!({"type": 3, "textContent": copy, "id": id}));
            }
        }
    }
    let mut events =
        vec![json!({"type": 4, "timestamp": 1, "data": {"href": "https://app.example.com/page"}})];
    let snapshot = json!({"node": {"type": 0, "id": 1, "childNodes": nodes}});
    events.push(if tc.draw(gs::booleans()) {
        json!({"type": 2, "timestamp": 1, "cv": "2024-10", "data": compressed(&snapshot)})
    } else {
        json!({"type": 2, "timestamp": 1, "data": snapshot})
    });
    events.extend(rules);
    with_escaped_slashes(tc, &Value::Array(events).to_string())
}

fn block_of(events: &str) -> Block {
    let inner = format!(
        r#"{{"event":"$snapshot_items","properties":{{"$session_id":"s","$window_id":"w1","$snapshot_items":{events}}}}}"#
    );
    let message = read_message(
        json!({"distinct_id": "d", "data": inner})
            .to_string()
            .into_bytes(),
    )
    .unwrap();
    let mut inspector = SessionInspector::default();
    let mut inspection = BlockInspection::default();
    inspector.observe_message(&mut inspection, &message);
    let found = inspection.finish();
    Block {
        session: SessionKey {
            team_id: 7,
            session_id: "s".to_owned(),
        },
        origin: Origin {
            tp: Tp {
                topic: "main",
                partition: 0,
            },
            start_offset: 100,
            end_offset: 105,
            flush_end_offset: 105,
        },
        messages: vec![message],
        stats: BlockStats::default(),
        moments: Vec::new(),
        image_urls: found.image_urls,
        font_urls: found.font_urls,
        url_limit: found.url_limit,
        edits: found.edits,
        declined: found.declined,
        unplaced: found.unplaced,
        visited_urls: Vec::new(),
        captured_at_ms: None,
    }
}

/// The stored lines, or `None` when the writer drops the block.
fn stored(tc: &TestCase, events: &str) -> Option<String> {
    let block = block_of(events);
    let (lines, _, counts): (Vec<u8>, _, WriterCounts) =
        write_block(&block, &[6; 32], "2026-10", || Ok(Vec::new())).unwrap();
    tc.event(counts.dropped.unwrap_or("stored"));
    counts
        .dropped
        .is_none()
        .then(|| String::from_utf8(lines).unwrap())
}

fn draw_page(tc: &TestCase) -> (Vec<Placed>, String) {
    let refused = tc.draw(gs::integers::<usize>().min_value(0).max_value(3));
    let accepted = tc.draw(gs::integers::<usize>().min_value(0).max_value(2));
    let placed: Vec<Placed> = (0..refused)
        .map(|index| draw_placed(tc, index, true))
        .chain((0..accepted).map(|index| draw_placed(tc, index, false)))
        .collect();
    let events = events(tc, &placed);
    (placed, events)
}

#[hegel::test]
#[ignore = "a search for bugs, run on demand"]
fn a_stored_block_holds_no_refused_url(tc: TestCase) {
    let (_, events) = draw_page(&tc);
    if let Some(lines) = stored(&tc, &events) {
        assert!(!lines.contains(SECRET), "{events}\n---\n{lines}");
    }
}

#[hegel::test]
#[ignore = "a search for bugs, run on demand"]
fn each_stored_line_is_a_window_and_an_event(tc: TestCase) {
    let (_, events) = draw_page(&tc);
    if let Some(lines) = stored(&tc, &events) {
        for line in lines.lines() {
            let parsed: Value = serde_json::from_str(line)
                .unwrap_or_else(|error| panic!("{error}: {line}\n---\n{events}"));
            assert!(
                parsed.as_array().is_some_and(|line| line.len() == 2),
                "{line}"
            );
        }
    }
}

#[hegel::test]
#[ignore = "a search for bugs, run on demand"]
fn a_stored_block_holds_no_accepted_url_in_an_image_slot(tc: TestCase) {
    let (_, events) = draw_page(&tc);
    if let Some(lines) = stored(&tc, &events) {
        assert!(!lines.contains(ACCEPTED), "{events}\n---\n{lines}");
    }
}

#[hegel::test]
#[ignore = "a search for bugs, run on demand"]
fn drops_a_block_only_for_an_escaped_image_set_candidate(tc: TestCase) {
    let (placed, events) = draw_page(&tc);
    let reason = placed
        .iter()
        .any(|placed| matches!(placed.slot, Slot::ImageSet) && placed.escaped);
    if !reason {
        assert!(stored(&tc, &events).is_some(), "{events}");
    }
}
