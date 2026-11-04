//! Property tests for the writer on pages that spell URLs in unusual ways: CSS escapes, quotes, comments and copies of
//! a URL outside its slot. They search for bugs rather than guard against them, so CI does not run them: each bug they
//! find gets an example test in `src/write.rs`. Run them with
//! `cargo test -p replay-recorder-v4 --test pbt_escapes -- --ignored`, and set `HEGEL_TEST_CASES` for a longer search.

use hegel::generators as gs;
use hegel::TestCase;
use replay_core_v4::inspect::session::{BlockInspection, SessionInspector};
use replay_core_v4::inspect::stats::BlockStats;
use replay_core_v4::refs::UrlAsset;
use replay_core_v4::scan::message::read_message;
use replay_core_v4::seal::image_url_key;
use replay_core_v4::url_policy::{redaction, Redaction};
use replay_recorder_v4::batch::{Block, Origin, SessionKey, Tp};
use replay_recorder_v4::urls::url_reference;
use replay_recorder_v4::write::{write_block, WriterCounts};
use serde_json::{json, Value};

/// The credential of every refused URL, in its query, userinfo, fragment or path. No other part of a page holds it.
const SECRET: &str = "pbtsecret";
/// The host label of every accepted URL. No other part of a generated page holds it.
const ACCEPTED: &str = "pbt-ok";
const TEAM_KEY: [u8; 32] = [6; 32];
const KEY_MONTH: &str = "2026-10";

const HOSTS: &[&str] = &[
    "cdn.example.com",
    "CDN.Example.COM",
    "bucket.s3.amazonaws.com",
];
/// Where a refused URL holds its credential, after its path.
const REFUSALS: &[&str] = &[
    "?token=",
    "?X-Amz-Signature=",
    "?sig=",
    "#access_token=",
    ";jsessionid=",
];

/// Past the 1,024 levels of JSON that the inspector reads, as each node takes two.
const DEEP_NODES: usize = 600;

#[derive(Debug, Clone, Copy, PartialEq)]
enum Slot {
    ImgSrc,
    Srcset,
    StyleAttribute,
    StyleSheet,
    FontFace(&'static str),
    ImageSet,
    CrossFade { in_image_set: bool },
    StyleRule,
    StyleChange,
    StyleObjectChange,
    StyleText,
    PictureSource,
    Href,
    FormAction,
    DataSrc,
    Filter,
    Import,
    SvgFill,
    AttributionSrc,
}

const SLOTS: &[Slot] = &[
    Slot::ImgSrc,
    Slot::Srcset,
    Slot::StyleAttribute,
    Slot::StyleSheet,
    Slot::FontFace("Brand"),
    Slot::FontFace("Roboto"),
    Slot::ImageSet,
    Slot::CrossFade {
        in_image_set: false,
    },
    Slot::CrossFade { in_image_set: true },
    Slot::StyleRule,
    Slot::StyleChange,
    Slot::StyleObjectChange,
    Slot::StyleText,
    Slot::PictureSource,
    Slot::Href,
    Slot::FormAction,
    Slot::DataSrc,
    Slot::Filter,
    Slot::Import,
    Slot::SvgFill,
    Slot::AttributionSrc,
];

impl Slot {
    fn is_css(self) -> bool {
        !matches!(
            self,
            Slot::ImgSrc
                | Slot::Srcset
                | Slot::PictureSource
                | Slot::Href
                | Slot::FormAction
                | Slot::DataSrc
                | Slot::AttributionSrc
        )
    }

    fn is_html_url(self) -> bool {
        matches!(
            self,
            Slot::ImgSrc | Slot::Href | Slot::FormAction | Slot::DataSrc
        )
    }

    /// No fetch takes the URL, so the block keeps it without its credentials, and with no reference.
    fn is_link(self) -> bool {
        matches!(
            self,
            Slot::Href
                | Slot::FormAction
                | Slot::DataSrc
                | Slot::Filter
                | Slot::Import
                | Slot::SvgFill
                | Slot::AttributionSrc
        )
    }

    /// After a restart the inspector cannot tell that a style element's text is CSS, so it names no URL there.
    fn names_an_accepted_url(self, shape: Shape) -> bool {
        !(self.is_link() || (shape.restart && self == Slot::StyleText))
    }

    /// The bundled font's reference names no URL.
    fn names_its_url(self) -> bool {
        !self.is_link() && self != Slot::FontFace("Roboto")
    }

    /// A set keeps its candidate as the page wrote it, so it cannot keep an escaped one, or one that another image function holds.
    fn drops_its_block(self, written: &str) -> bool {
        match self {
            Slot::ImageSet => written.contains('\\'),
            Slot::CrossFade { in_image_set } => in_image_set,
            _ => false,
        }
    }
}

/// A URL as the page writes it in its slot, and the spellings a copy of it can take elsewhere.
struct Placed {
    slot: Slot,
    written: String,
    copies: Vec<String>,
}

#[derive(Debug, Clone, Copy)]
struct Shape {
    /// The block holds no full snapshot, as after a restart, so the inspector does not know the nodes that its incremental snapshots name.
    restart: bool,
    compressed: bool,
    deep: bool,
}

fn draw_index(tc: &TestCase, len: usize) -> usize {
    tc.draw(gs::integers::<usize>().min_value(0).max_value(len - 1))
}

fn draw_url(tc: &TestCase, index: usize, refused: bool) -> String {
    let path = ["a.png", "img/b.png", "f.woff2"][draw_index(tc, 3)];
    let scheme = ["https://", "//"][draw_index(tc, 2)];
    if !refused {
        return format!("{scheme}{ACCEPTED}-{index}.example.com/{path}");
    }
    let host = HOSTS[draw_index(tc, HOSTS.len())];
    match draw_index(tc, 10) {
        0 => format!(
            "/{path}{}{SECRET}",
            REFUSALS[draw_index(tc, REFUSALS.len())]
        ),
        // A scheme starts with a letter, so the URL parser reads these as relative paths on the page's host.
        5 => format!(
            "{}{path}{}{SECRET}",
            ["1:", "9a:", ":"][draw_index(tc, 3)],
            REFUSALS[draw_index(tc, REFUSALS.len())]
        ),
        // A relative URL's host is the page's, which can be an Oracle bucket.
        6 => format!("/p/{SECRET}/n/ns/b/bucket/o/{path}"),
        // On a page of its scheme a browser reads this as a path, where the URL parser alone reads a host.
        7 => format!(
            "{}bcdn_token={SECRET}&expires=1/{path}",
            ["https:", "https:/"][draw_index(tc, 2)]
        ),
        1 => format!("{scheme}u:{SECRET}@{host}/{path}"),
        // The policy finds these tokens by their place in the path, and the Oracle one by its host too.
        2 => format!(
            "{scheme}objectstorage.us-ashburn-1.oraclecloud.com/p/{SECRET}/n/ns/b/bucket/o/{path}"
        ),
        3 => format!("{scheme}{host}/bcdn_token={SECRET}&expires=1/{path}"),
        4 => format!("{scheme}{host}/image/upload/s--{SECRET}--/v1/{path}"),
        _ => format!(
            "{scheme}{host}/{path}{}{SECRET}",
            REFUSALS[draw_index(tc, REFUSALS.len())]
        ),
    }
}

/// The bytes of `url` that a spelling must leave alone, so that the secret stays readable as plain text.
fn secret_range(url: &str) -> std::ops::Range<usize> {
    url.find(SECRET).map_or(0..0, |at| at..at + SECRET.len())
}

/// `url` as the URL parser reads it the same: the scheme and host in any letter case, the default port, a dot segment in the path, the first letter of the host percent-encoded, or fullwidth letters in the host, which IDNA maps to ASCII.
fn parsed_alike(tc: &TestCase, url: &str) -> String {
    let Some((scheme, rest)) = url.split_once("//") else {
        return url.to_owned();
    };
    let (authority, path) = rest.split_once('/').unwrap();
    let (userinfo, host) = authority
        .rsplit_once('@')
        .map_or(("", authority), |(userinfo, host)| (userinfo, host));
    let userinfo = if userinfo.is_empty() {
        String::new()
    } else {
        format!("{userinfo}@")
    };
    let scheme = if scheme.is_empty() {
        ""
    } else {
        ["https:", "HTTPS:", "hTtPs:"][draw_index(tc, 3)]
    };
    let mut host: String = match draw_index(tc, 3) {
        0 => host.to_owned(),
        1 => host.to_ascii_uppercase(),
        _ => host
            .chars()
            .enumerate()
            .map(|(at, ch)| {
                if at % 2 == 0 {
                    ch.to_ascii_uppercase()
                } else {
                    ch
                }
            })
            .collect(),
    };
    match draw_index(tc, 8) {
        0 | 1 => {
            let first = host.remove(0);
            host.insert_str(0, &format!("%{:02X}", first as u32));
        }
        2 => {
            host = host
                .chars()
                .enumerate()
                .map(|(at, ch)| match char::from_u32(ch as u32 + 0xFEE0) {
                    Some(fullwidth) if at % 2 == 1 && ch.is_ascii_alphabetic() => fullwidth,
                    _ => ch,
                })
                .collect()
        }
        _ => {}
    }
    if draw_index(tc, 6) == 0 {
        host.push('.');
    }
    let port = if draw_index(tc, 4) == 0 { ":443" } else { "" };
    let dots = ["", "", "./", "x/../"][draw_index(tc, 4)];
    format!("{scheme}//{userinfo}{host}{port}/{dots}{path}")
}

/// `url` with CSS escapes in the part before its query, so the secret stays readable as plain text.
fn css_escaped(tc: &TestCase, url: &str) -> String {
    let query_at = url.find('?').unwrap_or(url.len());
    let secret = secret_range(url);
    let mut out = String::new();
    for (at, ch) in url.char_indices() {
        let escape = at < query_at
            && !secret.contains(&at)
            && tc.draw(gs::integers::<u8>().min_value(0).max_value(5)) == 0;
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

/// `url` as an HTML attribute can hold it and a browser still loads it: the URL parser drops tabs and line breaks
/// anywhere, and reads a backslash as a slash.
fn html_spelled(tc: &TestCase, url: &str) -> String {
    let mut out = url.to_owned();
    if tc.draw(gs::booleans()) {
        out = out.replacen("//", ["\\\\", "/\\", "\\/"][draw_index(tc, 3)], 1);
    }
    let query_at = out.find('?').unwrap_or(out.len());
    for _ in 0..draw_index(tc, 3) {
        let at = draw_index(tc, query_at);
        let secret = secret_range(&out);
        if out.is_char_boundary(at) && !(secret.start < at && at < secret.end) {
            out.insert(at, ['\t', '\n'][draw_index(tc, 2)]);
        }
    }
    out
}

/// `url` with the C0 controls and spaces that the URL parser strips from both ends. CSS reads a NUL as U+FFFD and ends a string at a line break, so a CSS slot takes neither.
fn with_stripped_ends(tc: &TestCase, slot: Slot, url: &str) -> String {
    let ends: &[char] = if slot.is_css() {
        &[' ', '\t', '\u{1}', '\u{1f}']
    } else {
        &[' ', '\t', '\n', '\u{c}', '\u{0}', '\u{1}', '\u{1f}']
    };
    let end = || {
        if draw_index(tc, 4) == 0 {
            ends[draw_index(tc, ends.len())].to_string()
        } else {
            String::new()
        }
    };
    let start = end();
    format!("{start}{url}{}", end())
}

/// A spelling of `url` that a browser loads from the same place in `slot`, and that spelling with its CSS escapes decoded.
fn draw_spelling(tc: &TestCase, slot: Slot, url: &str) -> (String, String) {
    if !tc.draw(gs::booleans()) {
        return (url.to_owned(), url.to_owned());
    }
    let parsed = parsed_alike(tc, url);
    let mut spelled = parsed.clone();
    let css_escapes = slot.is_css() && tc.draw(gs::booleans());
    if css_escapes {
        spelled = css_escaped(tc, &spelled);
    } else if slot.is_html_url() && tc.draw(gs::booleans()) {
        spelled = html_spelled(tc, &spelled);
    }
    let written = with_stripped_ends(tc, slot, &spelled);
    let decoded = if !css_escapes {
        written.clone()
    } else {
        let start = &written[..written.find(&spelled).unwrap()];
        let end = &written[start.len() + spelled.len()..];
        format!("{start}{parsed}{end}")
    };
    (written, decoded)
}

/// `url` as the URL parser writes it, which is what a script reads back from a slot.
fn serialized(url: &str) -> String {
    let Some((_, rest)) = url.split_once("//") else {
        return format!("https://app.example.com{url}");
    };
    let (authority, tail) = rest.split_once('/').unwrap();
    format!("https://{}/{tail}", authority.to_ascii_lowercase())
}

/// The CSS `url()` of `written`, quoted or not, under any spelling of its name. A comment can follow a quoted string.
/// One before it makes a bad URL, which a browser never loads.
fn url_function(tc: &TestCase, written: &str) -> String {
    let name = ["url", "URL", "\\75 rl", "u\\72l"][draw_index(tc, 4)];
    let comment = if tc.draw(gs::booleans()) { "/*c*/" } else { "" };
    let space = if tc.draw(gs::booleans()) { " " } else { "" };
    let needs_quotes =
        written.contains(['(', ')', '"', '\'', '\\']) || written.contains(|ch: char| ch <= ' ');
    match draw_index(tc, 3) {
        0 if !needs_quotes => format!("{name}({written})"),
        1 => format!("{name}({space}\"{written}\"{comment})"),
        _ => format!("{name}({space}'{written}'{comment})"),
    }
}

/// `data` as posthog-js sends a compressed snapshot or list: gzip bytes, one per character.
fn compressed(data: &Value) -> String {
    replay_core_v4::compression::gzip(data.to_string().as_bytes())
        .unwrap()
        .iter()
        .map(|&byte| char::from(byte))
        .collect()
}

/// `json` with some slashes and letters of its strings escaped. A draw for each character would make a large page too many choices, so one drawn seed decides them.
fn with_json_escapes(tc: &TestCase, json: &str) -> String {
    let rate = [0, 4, 16][draw_index(tc, 3)];
    let mut state = tc.draw(gs::integers::<u64>()) | 1;
    let mut escape = || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        rate != 0 && state.is_multiple_of(rate)
    };
    let mut out = String::with_capacity(json.len());
    let mut in_string = false;
    let mut chars = json.chars();
    while let Some(ch) = chars.next() {
        match ch {
            '"' => {
                in_string = !in_string;
                out.push(ch);
            }
            '\\' => {
                out.push(ch);
                let escaped = chars.next().unwrap();
                out.push(escaped);
                if escaped == 'u' {
                    out.extend(chars.by_ref().take(4));
                }
            }
            '/' if in_string && escape() => out.push_str("\\/"),
            _ if in_string && ch.is_ascii_alphabetic() && escape() => {
                out.push_str(&format!("\\u{:04x}", ch as u32))
            }
            _ => out.push(ch),
        }
    }
    out
}

/// `text` as a JSON string holds it, the way a network body or a console log copies a slot's value.
fn json_text(text: &str) -> String {
    let quoted = serde_json::to_string(text).unwrap();
    quoted[1..quoted.len() - 1].to_owned()
}

/// A copy takes a spelling that the inspector records for the URL: as the page wrote it in the slot, as CSS decodes it, or as the URL parser writes it. A JSON copy holds the slot's spelling within its escaped ends.
fn draw_placed(tc: &TestCase, slots: &[Slot], url: String, refused: bool) -> Placed {
    let slot = slots[draw_index(tc, slots.len())];
    let (written, decoded) = draw_spelling(tc, slot, &url);
    let copies = if refused {
        let mut spellings = vec![written.clone(), decoded, serialized(&url)];
        let core = written.trim_matches(|ch: char| ch <= ' ');
        if json_text(core) == core {
            spellings.push(json_text(&written));
        }
        tc.draw(gs::vecs(gs::sampled_from(spellings)).max_size(2))
    } else {
        Vec::new()
    };
    Placed {
        slot,
        written,
        copies,
    }
}

fn draw_shape(tc: &TestCase) -> Shape {
    Shape {
        restart: tc.draw(gs::booleans()),
        compressed: tc.draw(gs::booleans()),
        deep: draw_index(tc, 16) == 0,
    }
}

fn element(id: &mut i64, tag: &str, attributes: Value) -> Value {
    *id += 1;
    json!({"type": 2, "tagName": tag, "attributes": attributes, "childNodes": [], "id": *id})
}

fn mutation(lists: Value) -> Value {
    let mut data = json!({"source": 0, "adds": [], "removes": [], "texts": [], "attributes": []});
    for (name, list) in lists.as_object().unwrap() {
        data[name] = list.clone();
    }
    json!({"type": 3, "timestamp": 2, "data": data})
}

/// The page's events. Each URL is in its slot and each copy in an `alt` attribute or a text node. A full snapshot
/// holds the nodes, or after a restart a mutation adds them under a node that the inspector does not know.
fn events(tc: &TestCase, placed: &[Placed], shape: Shape) -> String {
    let mut id = 1;
    let mut added = Vec::new();
    let mut known = Vec::new();
    let mut incremental = Vec::new();
    for Placed {
        slot,
        written,
        copies,
    } in placed
    {
        let function = || url_function(tc, written);
        match slot {
            Slot::ImgSrc => added.push(element(&mut id, "img", json!({"src": written}))),
            Slot::Srcset => added.push(element(
                &mut id,
                "img",
                json!({"srcset": format!("{written} 1x, https://cdn.example.com/other.png 2x")}),
            )),
            Slot::StyleAttribute => added.push(element(
                &mut id,
                "div",
                json!({"style": format!("background-image:{}", function())}),
            )),
            Slot::StyleSheet => added.push(element(
                &mut id,
                "style",
                json!({"_cssText": format!(".a{{background:{}}}", function())}),
            )),
            Slot::FontFace(family) => added.push(element(
                &mut id,
                "style",
                json!({"_cssText": format!("@font-face{{font-family:{family};src:{}}}", function())}),
            )),
            Slot::ImageSet => added.push(element(
                &mut id,
                "div",
                json!({"style": format!("background-image:image-set({} 1x)", function())}),
            )),
            Slot::CrossFade { in_image_set } => {
                let fade = format!(
                    "-webkit-cross-fade({}, url(https://cdn.example.com/other.png), 50%)",
                    function()
                );
                let image = if *in_image_set {
                    format!("image-set({fade} 1x)")
                } else {
                    fade
                };
                added.push(element(
                    &mut id,
                    "div",
                    json!({"style": format!("background-image:{image}")}),
                ));
            }
            Slot::StyleRule => incremental.push(json!({"type": 3, "timestamp": 2, "data": {"source": 8, "id": 3,
                "replaceSync": format!(".r{{background:{}}}", function())}})),
            Slot::StyleChange => {
                known.push(element(&mut id, "div", json!({})));
                incremental.push(mutation(json!({"attributes": [{"id": id,
                    "attributes": {"style": format!("background-image:{}", function())}}]})));
            }
            Slot::StyleObjectChange => {
                known.push(element(&mut id, "div", json!({})));
                incremental.push(mutation(json!({"attributes": [{"id": id,
                    "attributes": {"style": {"background-image": function()}}}]})));
            }
            Slot::StyleText => {
                let mut style = element(&mut id, "style", json!({}));
                id += 1;
                style["childNodes"] =
                    json!([{"type": 3, "textContent": "", "isStyle": true, "id": id}]);
                known.push(style);
                incremental.push(mutation(json!({"texts": [{"id": id,
                    "value": format!(".t{{background:{}}}", function())}]})));
            }
            Slot::Href => added.push(element(&mut id, "a", json!({"href": written}))),
            Slot::FormAction => added.push(element(&mut id, "form", json!({"action": written}))),
            Slot::DataSrc => added.push(element(&mut id, "img", json!({"data-src": written}))),
            Slot::Filter => added.push(element(
                &mut id,
                "div",
                json!({"style": format!("filter:{}", function())}),
            )),
            Slot::Import => added.push(element(
                &mut id,
                "style",
                json!({"_cssText": format!("@import {};", function())}),
            )),
            Slot::SvgFill => added.push(element(&mut id, "rect", json!({"fill": function()}))),
            Slot::AttributionSrc => added.push(element(
                &mut id,
                "img",
                json!({"attributionsrc": format!("https://cdn.example.com/x {written}")}),
            )),
            Slot::PictureSource => {
                known.push(element(&mut id, "picture", json!({})));
                let parent = id;
                let source = element(
                    &mut id,
                    "source",
                    json!({"srcset": format!("{written} 1x")}),
                );
                incremental.push(mutation(
                    json!({"adds": [{"parentId": parent, "nextId": null, "node": source}]}),
                ));
            }
        }
        for copy in copies {
            if tc.draw(gs::booleans()) {
                added.push(element(&mut id, "img", json!({"alt": copy})));
            } else {
                id += 1;
                added.push(json!({"type": 3, "textContent": copy, "id": id}));
            }
        }
    }
    if shape.deep {
        added = (0..DEEP_NODES).fold(added, |children, _| {
            let mut parent = element(&mut id, "div", json!({}));
            parent["childNodes"] = Value::Array(children);
            vec![parent]
        });
    }
    let mut events = Vec::new();
    if shape.restart {
        let adds: Vec<Value> = added
            .into_iter()
            .map(|node| json!({"parentId": 1, "nextId": null, "node": node}))
            .collect();
        events.push(if shape.compressed {
            json!({"type": 3, "timestamp": 1, "cv": "2024-10", "data": {"source": 0, "adds": compressed(&json!(adds)),
                "removes": compressed(&json!([])), "texts": compressed(&json!([])), "attributes": compressed(&json!([]))}})
        } else {
            mutation(json!({"adds": adds}))
        });
    } else {
        events.push(
            json!({"type": 4, "timestamp": 1, "data": {"href": "https://app.example.com/page"}}),
        );
        known.extend(added);
        let snapshot = json!({"node": {"type": 0, "id": 1, "childNodes": known}});
        events.push(if shape.compressed {
            json!({"type": 2, "timestamp": 1, "cv": "2024-10", "data": compressed(&snapshot)})
        } else {
            json!({"type": 2, "timestamp": 1, "data": snapshot})
        });
    }
    events.extend(incremental);
    with_json_escapes(tc, &Value::Array(events).to_string())
}

fn drop_reasons(placed: &[Placed], shape: Shape) -> Vec<&'static str> {
    let mut reasons = Vec::new();
    if placed
        .iter()
        .any(|placed| placed.slot.drops_its_block(&placed.written))
    {
        reasons.push("unplaced_slot");
    }
    if shape.deep {
        reasons.extend(["too_deep_json", "unreadable_message"]);
    }
    reasons
}

fn block_of(events: &str) -> Option<Block> {
    let inner = format!(
        r#"{{"event":"$snapshot_items","properties":{{"$session_id":"s","$window_id":"w1","$snapshot_items":{events}}}}}"#
    );
    let message = read_message(
        json!({"distinct_id": "d", "data": inner})
            .to_string()
            .into_bytes(),
    )
    .ok()?;
    let mut inspector = SessionInspector::default();
    let mut inspection = BlockInspection::default();
    inspector.observe_message(&mut inspection, &message);
    let found = inspection.finish();
    Some(Block {
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
        unplaced: found.unplaced,
        visited_urls: Vec::new(),
        captured_at_ms: None,
    })
}

/// The stored lines, or why the block is not stored. The recorder skips a message it cannot read.
fn stored(tc: &TestCase, events: &str) -> Result<String, &'static str> {
    let Some(block) = block_of(events) else {
        tc.event("unreadable_message");
        return Err("unreadable_message");
    };
    let (lines, _, counts): (Vec<u8>, _, WriterCounts) =
        write_block(&block, &TEAM_KEY, KEY_MONTH, || Ok(Vec::new())).unwrap();
    tc.event(counts.dropped.unwrap_or("stored"));
    match counts.dropped {
        Some(reason) => Err(reason),
        None => Ok(String::from_utf8(lines).unwrap()),
    }
}

/// `lines` with each JSON line written again, so that an escape in a string does not hide what the string holds.
fn decoded(lines: &str) -> String {
    lines
        .lines()
        .map(|line| {
            serde_json::from_str::<Value>(line)
                .map_or_else(|_| line.to_owned(), |value| value.to_string())
        })
        .collect::<Vec<_>>()
        .join("\n")
}

struct Page {
    placed: Vec<Placed>,
    shape: Shape,
    events: String,
}

fn draw_page(tc: &TestCase) -> Page {
    let shape = draw_shape(tc);
    let refused = tc.draw(gs::integers::<usize>().min_value(0).max_value(3));
    let accepted = tc.draw(gs::integers::<usize>().min_value(0).max_value(2));
    // A link keeps an accepted URL as the page wrote it, so only a slot that names one takes one.
    let image_slots: Vec<Slot> = SLOTS
        .iter()
        .copied()
        .filter(|slot| slot.names_an_accepted_url(shape))
        .collect();
    let placed: Vec<Placed> = (0..refused)
        .map(|index| (index, true))
        .chain((0..accepted).map(|index| (index, false)))
        .map(|(index, refused)| {
            let url = draw_url(tc, index, refused);
            let slots = if refused { SLOTS } else { &image_slots };
            draw_placed(tc, slots, url, refused)
        })
        .collect();
    let events = events(tc, &placed, shape);
    Page {
        placed,
        shape,
        events,
    }
}

/// v4 stores pages unscrubbed, so each copy of a URL outside a URL slot keeps its text, and a slot keeps no credential.
#[hegel::test]
#[ignore = "a search for bugs, run on demand"]
fn a_stored_block_holds_a_credential_only_in_copies(tc: TestCase) {
    let page = draw_page(&tc);
    let Ok(lines) = stored(&tc, &page.events) else {
        return;
    };
    let mut rest = decoded(&lines);
    let mut copies: Vec<String> = page
        .placed
        .iter()
        .flat_map(|placed| &placed.copies)
        .map(|copy| json!(copy).to_string())
        .collect();
    copies.sort();
    for copy in copies.chunk_by(|a, b| a == b) {
        assert_eq!(
            rest.matches(&copy[0]).count(),
            copy.len(),
            "{}\n---\n{lines}",
            page.events
        );
        rest = rest.replace(&copy[0], "");
    }
    let rest = rest
        .replace("\\t", "")
        .replace("\\n", "")
        .to_ascii_lowercase();
    assert!(!rest.contains(SECRET), "{}\n---\n{lines}", page.events);
}

/// Every spelling of a refused URL that a browser loads holds a credential that the policy finds, and loses it.
#[hegel::test]
#[ignore = "a search for bugs, run on demand"]
fn a_url_without_its_credentials_holds_no_secret(tc: TestCase) {
    let url = draw_url(&tc, 0, true);
    let (written, _) = draw_spelling(&tc, Slot::ImgSrc, &url);
    let kept = match redaction(&written) {
        Redaction::Redacted(kept) => kept,
        // The block keeps a decline marker in its place.
        Redaction::Unread => return,
        Redaction::Clean => panic!("{written:?}"),
    };
    assert!(
        !kept
            .replace(['\t', '\n'], "")
            .to_ascii_lowercase()
            .contains(SECRET),
        "{written:?} => {kept:?}"
    );
}

#[hegel::test]
#[ignore = "a search for bugs, run on demand"]
fn each_stored_line_is_a_window_and_an_event(tc: TestCase) {
    let page = draw_page(&tc);
    if let Ok(lines) = stored(&tc, &page.events) {
        for line in lines.lines() {
            let parsed: Value = serde_json::from_str(line)
                .unwrap_or_else(|error| panic!("{error}: {line}\n---\n{}", page.events));
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
    let page = draw_page(&tc);
    if let Ok(lines) = stored(&tc, &page.events) {
        assert!(
            !decoded(&lines).to_ascii_lowercase().contains(ACCEPTED),
            "{}\n---\n{lines}",
            page.events
        );
    }
}

#[hegel::test]
#[ignore = "a search for bugs, run on demand"]
fn drops_a_block_only_for_a_reason_the_page_holds(tc: TestCase) {
    let page = draw_page(&tc);
    if let Err(reason) = stored(&tc, &page.events) {
        assert!(
            drop_reasons(&page.placed, page.shape).contains(&reason),
            "{reason}: {}",
            page.events
        );
    }
}

#[hegel::test]
#[ignore = "a search for bugs, run on demand"]
fn each_spelling_of_a_url_gets_the_reference_its_fetch_job_names(tc: TestCase) {
    let shape = Shape {
        deep: false,
        ..draw_shape(&tc)
    };
    let url = draw_url(&tc, 0, false);
    let slots: Vec<Slot> = SLOTS
        .iter()
        .copied()
        .filter(|slot| !slot.drops_its_block("") && slot.names_an_accepted_url(shape))
        .collect();
    let count = tc.draw(gs::integers::<usize>().min_value(2).max_value(4));
    let placed: Vec<Placed> = (0..count)
        .map(|_| draw_placed(&tc, &slots, url.clone(), false))
        .collect();
    let events = events(&tc, &placed, shape);
    let Ok(lines) = stored(&tc, &events) else {
        return;
    };
    let (_, reference) = url_reference(
        &url,
        UrlAsset::Image,
        7,
        KEY_MONTH,
        &image_url_key(&TEAM_KEY),
    )
    .unwrap();
    let hash = reference.rsplit(':').next().unwrap();
    let naming = placed
        .iter()
        .filter(|placed| placed.slot.names_its_url())
        .count();
    assert_eq!(
        decoded(&lines).matches(hash).count(),
        naming,
        "{events}\n---\n{lines}"
    );
}
