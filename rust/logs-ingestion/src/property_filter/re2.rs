//! `new RE2(pattern, flags).test(str)` from node-re2 1.22.1, on the Rust `regex` engine.
//!
//! node-re2 first rewrites the JavaScript pattern text (`translateRegExp` in `lib/new.cc`), then
//! RE2 parses it in Perl mode. This module ports both steps. The RE2 step is a parser that accepts
//! exactly what RE2's `parse.cc` accepts and writes an equivalent Rust pattern. A pattern that RE2
//! rejects (look-around, back-references, `\Z`, `(?x)`, stacked repetition, a count above 1000)
//! gives an error here too, so the caller sees the same "fails to compile" result.
//!
//! The Rust pattern differs from the RE2 text where the two engines disagree on syntax:
//! - `\d`, `\s`, `\w` and `\b` are ASCII in RE2 and Unicode in Rust, so they become explicit
//!   classes and `(?-u:\b)`. RE2's `\s` has no `\v`.
//! - RE2 reads `[a[b]]` as the class `[a[b]` and a literal `]`, and treats `&&`, `--`, `~~`
//!   in a class as literal text. Every class is written again with explicit escapes.
//! - RE2 reads a `{` that does not start a valid count as a literal.
//! - RE2 accepts surrogate code points (`\x{D800}`, or a lone surrogate in the pattern); they can
//!   never match valid UTF-8. Rust rejects them, so they become a class that matches nothing.
//! - `\p{C}` in RE2 has no unassigned code points; `\p{Cs}` is not a Rust class.
//!
//! Not reproduced: RE2's program size limit (`max_mem`, 8 MiB) and Rust's size and nesting
//! limits differ, so a very large pattern can compile in one engine and fail in the other.
//! Unicode table versions can also differ between the vendored RE2 and the `regex` crate.

use std::collections::HashSet;
use std::sync::OnceLock;

use regex::bytes::{Regex, RegexBuilder};

#[derive(Debug, Clone)]
pub struct Re2 {
    regex: Regex,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Re2Error(pub String);

impl std::fmt::Display for Re2Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for Re2Error {}

impl Re2 {
    /// `new RE2(pattern, flags)`. `pattern` is the UTF-8 that V8 writes for the JavaScript string:
    /// WTF-8, where a lone surrogate takes its 3-byte form. Only the `i`, `m` and `s` flags change
    /// what `test` returns.
    pub fn new(pattern: &[u8], flags: &str) -> Result<Re2, Re2Error> {
        let ignore_case = flags.contains('i');
        let multiline = flags.contains('m');
        let dot_all = flags.contains('s');
        let translated = node_translate(pattern, multiline);
        let body = Parser::new(&translated).parse()?;
        let mut rust = String::with_capacity(body.len() + 8);
        if ignore_case || dot_all {
            rust.push_str("(?");
            if ignore_case {
                rust.push('i');
            }
            if dot_all {
                rust.push('s');
            }
            rust.push(')');
        }
        rust.push_str(&body);
        let regex = RegexBuilder::new(&rust)
            .nest_limit(MAX_NESTING as u32)
            .build()
            .map_err(|e| Re2Error(e.to_string()))?;
        Ok(Re2 { regex })
    }

    /// `new RE2(pattern)` with no flags, as `createTrackedRE2(pattern, undefined)` calls it.
    pub fn without_flags(pattern: &str) -> Result<Re2, Re2Error> {
        Re2::new(pattern.as_bytes(), "")
    }

    /// `re.test(input)` for a regex without the `g` or `y` flag. node-re2 writes the input as
    /// UTF-8 with U+FFFD for a lone surrogate, so callers pass the lossy UTF-8 form.
    pub fn test(&self, input: &str) -> bool {
        self.regex.is_match(input.as_bytes())
    }
}

fn is_node_hexadecimal(ch: u8) -> bool {
    // node-re2's own check accepts every ASCII letter, not only a-f.
    ch.is_ascii_digit() || ch.is_ascii_alphabetic()
}

fn utf8_char_size(ch: u8) -> usize {
    // The same lookup as node-re2's `getUtf8CharSize`.
    (((0xE500_0000u32 >> ((ch >> 3) & 0x1E)) & 3) + 1) as usize
}

/// The long Unicode property names that node-re2 maps to RE2's short names.
fn unicode_class_alias(name: &[u8]) -> Option<&'static str> {
    Some(match name {
        b"Uppercase_Letter" => "Lu",
        b"Lowercase_Letter" => "Ll",
        b"Titlecase_Letter" => "Lt",
        b"Cased_Letter" => "LC",
        b"Modifier_Letter" => "Lm",
        b"Other_Letter" => "Lo",
        b"Letter" => "L",
        b"Nonspacing_Mark" => "Mn",
        b"Spacing_Mark" => "Mc",
        b"Enclosing_Mark" => "Me",
        b"Mark" => "M",
        b"Decimal_Number" => "Nd",
        b"Letter_Number" => "Nl",
        b"Other_Number" => "No",
        b"Number" => "N",
        b"Connector_Punctuation" => "Pc",
        b"Dash_Punctuation" => "Pd",
        b"Open_Punctuation" => "Ps",
        b"Close_Punctuation" => "Pe",
        b"Initial_Punctuation" => "Pi",
        b"Final_Punctuation" => "Pf",
        b"Other_Punctuation" => "Po",
        b"Punctuation" => "P",
        b"Math_Symbol" => "Sm",
        b"Currency_Symbol" => "Sc",
        b"Modifier_Symbol" => "Sk",
        b"Other_Symbol" => "So",
        b"Symbol" => "S",
        b"Space_Separator" => "Zs",
        b"Line_Separator" => "Zl",
        b"Paragraph_Separator" => "Zp",
        b"Separator" => "Z",
        b"Control" => "Cc",
        b"Format" => "Cf",
        b"Surrogate" => "Cs",
        b"Private_Use" => "Co",
        b"Unassigned" => "Cn",
        b"Other" => "C",
        _ => return None,
    })
}

/// node-re2's `translateRegExp`: a text rewrite before RE2 sees the pattern. It runs on the raw
/// text, so it also rewrites inside character classes (`[(?<a]` gains a `P`).
fn node_translate(data: &[u8], multiline: bool) -> Vec<u8> {
    let size = data.len();
    let mut out: Vec<u8> = Vec::with_capacity(size + 8);
    if size == 0 {
        out.extend_from_slice(b"(?:)");
    } else if multiline {
        out.extend_from_slice(b"(?m)");
    }
    let hex = b"0123456789ABCDEF";
    let mut i = 0;
    while i < size {
        let ch = data[i];
        if ch == b'\\' && i + 1 < size {
            let next = data[i + 1];
            match next {
                b'\\' => {
                    out.extend_from_slice(b"\\\\");
                    i += 2;
                    continue;
                }
                b'c' => {
                    if i + 2 < size && data[i + 2].is_ascii_uppercase() {
                        let code = data[i + 2] - b'@';
                        out.extend_from_slice(b"\\x");
                        out.push(hex[((code / 16) & 15) as usize]);
                        out.push(hex[(code & 15) as usize]);
                        i += 3;
                        continue;
                    }
                    out.extend_from_slice(b"\\c");
                    i += 2;
                    continue;
                }
                b'u' => {
                    if i + 2 < size {
                        let first = data[i + 2];
                        if is_node_hexadecimal(first) {
                            out.extend_from_slice(b"\\x{");
                            out.push(first);
                            i += 3;
                            let mut j = 0;
                            while j < 3 && i < size {
                                if !is_node_hexadecimal(data[i]) {
                                    break;
                                }
                                out.push(data[i]);
                                i += 1;
                                j += 1;
                            }
                            out.push(b'}');
                            continue;
                        } else if first == b'{' {
                            out.extend_from_slice(b"\\x");
                            i += 2;
                            continue;
                        }
                    }
                    out.extend_from_slice(b"\\u");
                    i += 2;
                    continue;
                }
                b'p' | b'P' => {
                    if i + 2 < size && data[i + 2] == b'{' {
                        let mut j = i + 3;
                        while j < size && data[j] != b'}' {
                            j += 1;
                        }
                        if j < size {
                            out.push(b'\\');
                            out.push(next);
                            let raw = &data[i + 3..j];
                            let name: &[u8] = if let Some(alias) = unicode_class_alias(raw) {
                                alias.as_bytes()
                            } else if raw.len() > 7 && raw.starts_with(b"Script=") {
                                &raw[7..]
                            } else if raw.len() > 3 && raw.starts_with(b"sc=") {
                                &raw[3..]
                            } else {
                                raw
                            };
                            if name.len() == 1 {
                                out.extend_from_slice(name);
                            } else {
                                out.push(b'{');
                                out.extend_from_slice(name);
                                out.push(b'}');
                            }
                            i = j + 1;
                            continue;
                        }
                    }
                    out.push(b'\\');
                    out.push(next);
                    i += 2;
                    continue;
                }
                _ => {
                    out.push(b'\\');
                    let n = utf8_char_size(next);
                    let end = (i + 1 + n).min(size);
                    out.extend_from_slice(&data[i + 1..end]);
                    i += n + 1;
                    continue;
                }
            }
        } else if ch == b'/' {
            out.extend_from_slice(b"\\/");
            i += 1;
            continue;
        } else if ch == b'('
            && i + 2 < size
            && data[i + 1] == b'?'
            && data[i + 2] == b'<'
            && (i + 3 >= size || (data[i + 3] != b'=' && data[i + 3] != b'!'))
        {
            out.extend_from_slice(b"(?P<");
            i += 3;
            continue;
        }
        let n = utf8_char_size(ch);
        let end = (i + n).min(size);
        out.extend_from_slice(&data[i..end]);
        i += n;
    }
    out
}

const RUNE_MAX: u32 = 0x10FFFF;
const MAX_REPEAT: u32 = 1000;
/// A class that matches nothing: what a surrogate code point matches in valid UTF-8.
const NEVER: &str = r"[^\x{0}-\x{10FFFF}]";
const ANY: &str = r"[\x{0}-\x{10FFFF}]";

/// Decodes one rune the way RE2's `chartorune` does. Surrogates decode as themselves.
fn decode_rune(b: &[u8], pos: usize) -> Option<(u32, usize)> {
    let first = *b.get(pos)?;
    let cont = |k: usize| -> Option<u32> {
        let c = *b.get(pos + k)?;
        (c & 0xC0 == 0x80).then_some((c & 0x3F) as u32)
    };
    if first < 0x80 {
        Some((first as u32, 1))
    } else if first & 0xE0 == 0xC0 {
        Some(((((first & 0x1F) as u32) << 6) | cont(1)?, 2))
    } else if first & 0xF0 == 0xE0 {
        Some((
            (((first & 0x0F) as u32) << 12) | (cont(1)? << 6) | cont(2)?,
            3,
        ))
    } else if first & 0xF8 == 0xF0 {
        let r = (((first & 0x07) as u32) << 18) | (cont(1)? << 12) | (cont(2)? << 6) | cont(3)?;
        (r <= RUNE_MAX).then_some((r, 4))
    } else {
        None
    }
}

fn is_surrogate(r: u32) -> bool {
    (0xD800..=0xDFFF).contains(&r)
}

fn literal(r: u32) -> String {
    if is_surrogate(r) {
        return NEVER.to_string();
    }
    match char::from_u32(r) {
        Some(c) if c.is_ascii_alphanumeric() || (!c.is_ascii() && !c.is_whitespace()) => {
            c.to_string()
        }
        _ => format!("\\x{{{r:X}}}"),
    }
}

/// One member of a character class, in Rust syntax that is valid inside `[...]`.
enum ClassItem {
    Range(u32, u32),
    Nested(String),
}

fn push_range(out: &mut String, lo: u32, hi: u32) {
    let mut emit = |a: u32, b: u32| {
        if a == b {
            out.push_str(&format!("\\x{{{a:X}}}"));
        } else {
            out.push_str(&format!("\\x{{{a:X}}}-\\x{{{b:X}}}"));
        }
    };
    if lo <= 0xD7FF {
        emit(lo, hi.min(0xD7FF));
    }
    if hi >= 0xE000 {
        emit(lo.max(0xE000), hi);
    }
}

fn class_text(negated: bool, items: &[ClassItem]) -> String {
    let mut body = String::new();
    for item in items {
        match item {
            ClassItem::Range(lo, hi) => push_range(&mut body, *lo, *hi),
            ClassItem::Nested(text) => body.push_str(text),
        }
    }
    if body.is_empty() {
        return if negated { ANY } else { NEVER }.to_string();
    }
    format!("[{}{}]", if negated { "^" } else { "" }, body)
}

/// RE2's Perl classes. `\s` has no `\v`.
fn perl_class(c: u8) -> Option<(bool, &'static str)> {
    Some(match c {
        b'd' => (false, r"0-9"),
        b'D' => (true, r"0-9"),
        b's' => (false, r"\t\n\x0C\r "),
        b'S' => (true, r"\t\n\x0C\r "),
        b'w' => (false, r"0-9A-Za-z_"),
        b'W' => (true, r"0-9A-Za-z_"),
        _ => return None,
    })
}

/// RE2's POSIX classes, all ASCII.
fn posix_class(name: &[u8]) -> Option<&'static str> {
    Some(match name {
        b"alnum" => r"0-9A-Za-z",
        b"alpha" => r"A-Za-z",
        b"ascii" => r"\x00-\x7F",
        b"blank" => r"\t ",
        b"cntrl" => r"\x00-\x1F\x7F",
        b"digit" => r"0-9",
        b"graph" => r"!-~",
        b"lower" => r"a-z",
        b"print" => r" -~",
        b"punct" => r"!-/:-@\[-`\{-~",
        b"space" => r"\t-\r ",
        b"upper" => r"A-Z",
        b"word" => r"0-9A-Za-z_",
        b"xdigit" => r"0-9A-Fa-f",
        _ => return None,
    })
}

/// The scripts and general categories in RE2's `unicode_groups.cc`, plus `Any`.
const UNICODE_GROUPS: &[&str] = &[
    "Adlam",
    "Ahom",
    "Anatolian_Hieroglyphs",
    "Arabic",
    "Armenian",
    "Avestan",
    "Balinese",
    "Bamum",
    "Bassa_Vah",
    "Batak",
    "Bengali",
    "Bhaiksuki",
    "Bopomofo",
    "Brahmi",
    "Braille",
    "Buginese",
    "Buhid",
    "C",
    "Canadian_Aboriginal",
    "Carian",
    "Caucasian_Albanian",
    "Cc",
    "Cf",
    "Chakma",
    "Cham",
    "Cherokee",
    "Chorasmian",
    "Co",
    "Common",
    "Coptic",
    "Cs",
    "Cuneiform",
    "Cypriot",
    "Cypro_Minoan",
    "Cyrillic",
    "Deseret",
    "Devanagari",
    "Dives_Akuru",
    "Dogra",
    "Duployan",
    "Egyptian_Hieroglyphs",
    "Elbasan",
    "Elymaic",
    "Ethiopic",
    "Georgian",
    "Glagolitic",
    "Gothic",
    "Grantha",
    "Greek",
    "Gujarati",
    "Gunjala_Gondi",
    "Gurmukhi",
    "Han",
    "Hangul",
    "Hanifi_Rohingya",
    "Hanunoo",
    "Hatran",
    "Hebrew",
    "Hiragana",
    "Imperial_Aramaic",
    "Inherited",
    "Inscriptional_Pahlavi",
    "Inscriptional_Parthian",
    "Javanese",
    "Kaithi",
    "Kannada",
    "Katakana",
    "Kawi",
    "Kayah_Li",
    "Kharoshthi",
    "Khitan_Small_Script",
    "Khmer",
    "Khojki",
    "Khudawadi",
    "L",
    "Lao",
    "Latin",
    "Lepcha",
    "Limbu",
    "Linear_A",
    "Linear_B",
    "Lisu",
    "Ll",
    "Lm",
    "Lo",
    "Lt",
    "Lu",
    "Lycian",
    "Lydian",
    "M",
    "Mahajani",
    "Makasar",
    "Malayalam",
    "Mandaic",
    "Manichaean",
    "Marchen",
    "Masaram_Gondi",
    "Mc",
    "Me",
    "Medefaidrin",
    "Meetei_Mayek",
    "Mende_Kikakui",
    "Meroitic_Cursive",
    "Meroitic_Hieroglyphs",
    "Miao",
    "Mn",
    "Modi",
    "Mongolian",
    "Mro",
    "Multani",
    "Myanmar",
    "N",
    "Nabataean",
    "Nag_Mundari",
    "Nandinagari",
    "Nd",
    "New_Tai_Lue",
    "Newa",
    "Nko",
    "Nl",
    "No",
    "Nushu",
    "Nyiakeng_Puachue_Hmong",
    "Ogham",
    "Ol_Chiki",
    "Old_Hungarian",
    "Old_Italic",
    "Old_North_Arabian",
    "Old_Permic",
    "Old_Persian",
    "Old_Sogdian",
    "Old_South_Arabian",
    "Old_Turkic",
    "Old_Uyghur",
    "Oriya",
    "Osage",
    "Osmanya",
    "P",
    "Pahawh_Hmong",
    "Palmyrene",
    "Pau_Cin_Hau",
    "Pc",
    "Pd",
    "Pe",
    "Pf",
    "Phags_Pa",
    "Phoenician",
    "Pi",
    "Po",
    "Ps",
    "Psalter_Pahlavi",
    "Rejang",
    "Runic",
    "S",
    "Samaritan",
    "Saurashtra",
    "Sc",
    "Sharada",
    "Shavian",
    "Siddham",
    "SignWriting",
    "Sinhala",
    "Sk",
    "Sm",
    "So",
    "Sogdian",
    "Sora_Sompeng",
    "Soyombo",
    "Sundanese",
    "Syloti_Nagri",
    "Syriac",
    "Tagalog",
    "Tagbanwa",
    "Tai_Le",
    "Tai_Tham",
    "Tai_Viet",
    "Takri",
    "Tamil",
    "Tangsa",
    "Tangut",
    "Telugu",
    "Thaana",
    "Thai",
    "Tibetan",
    "Tifinagh",
    "Tirhuta",
    "Toto",
    "Ugaritic",
    "Vai",
    "Vithkuqi",
    "Wancho",
    "Warang_Citi",
    "Yezidi",
    "Yi",
    "Z",
    "Zanabazar_Square",
    "Zl",
    "Zp",
    "Zs",
    "Any",
];

/// A Unicode group as a class member. `Cs` is empty in valid UTF-8, so it matches nothing.
fn unicode_group_item(name: &str, negated: bool) -> ClassItem {
    let positive = match name {
        // RE2's C has no unassigned code points; Rust's does.
        "C" => r"[\p{Cc}\p{Cf}\p{Co}]".to_string(),
        "Cs" => NEVER.to_string(),
        other => format!("\\p{{{other}}}"),
    };
    if !negated {
        return ClassItem::Nested(positive);
    }
    ClassItem::Nested(match name {
        "C" => r"[^\p{Cc}\p{Cf}\p{Co}]".to_string(),
        "Cs" => ANY.to_string(),
        other => format!("\\P{{{other}}}"),
    })
}

fn capture_name_regex() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"^[\p{Lu}\p{Ll}\p{Lt}\p{Lm}\p{Lo}\p{Nl}\p{Mn}\p{Mc}\p{Nd}\p{Pc}]+$")
            .expect("static pattern")
    })
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum PieceKind {
    Atom,
    /// An empty-width assertion. Rust needs a group around it before a repetition.
    Assertion,
    /// `(?i)` and friends: not a repetition argument.
    Flags,
}

/// A counted repetition in the tree, for RE2's `RepetitionWalker`.
#[derive(Clone)]
struct RepNode {
    divisor: u32,
    depth: usize,
    children: Vec<RepNode>,
}

/// The `nest_limit` that `Re2::new` gives the Rust regex builder. Each group and each nested
/// repetition is one level there, so a pattern past this depth fails to compile either way.
/// The parser stops at it first, so deep input cannot overflow the stack. See PORTING.md.
const MAX_NESTING: usize = 1000;

fn walk(node: &RepNode, arg: u32) -> u32 {
    let arg = arg.checked_div(node.divisor).unwrap_or(arg);
    node.children
        .iter()
        .map(|c| walk(c, arg))
        .fold(arg, u32::min)
}

struct Piece {
    text: String,
    kind: PieceKind,
    repeated: bool,
    reps: Vec<RepNode>,
}

struct Frame {
    open: String,
    alternatives: Vec<String>,
    reps: Vec<RepNode>,
    current: Vec<Piece>,
}

impl Frame {
    fn new(open: String) -> Self {
        Frame {
            open,
            alternatives: Vec::new(),
            reps: Vec::new(),
            current: Vec::new(),
        }
    }

    fn finish_alternative(&mut self) {
        let mut text = String::new();
        for piece in self.current.drain(..) {
            text.push_str(&piece.text);
            self.reps.extend(piece.reps);
        }
        self.alternatives.push(text);
    }
}

struct Parser<'a> {
    s: &'a [u8],
    pos: usize,
    stack: Vec<Frame>,
    names: HashSet<String>,
}

fn err<T>(message: &str) -> Result<T, Re2Error> {
    Err(Re2Error(message.to_string()))
}

impl<'a> Parser<'a> {
    fn new(s: &'a [u8]) -> Self {
        Parser {
            s,
            pos: 0,
            stack: vec![Frame::new(String::new())],
            names: HashSet::new(),
        }
    }

    fn rest(&self) -> &'a [u8] {
        &self.s[self.pos..]
    }

    fn peek(&self, k: usize) -> Option<u8> {
        self.s.get(self.pos + k).copied()
    }

    fn next_rune(&mut self) -> Result<u32, Re2Error> {
        match decode_rune(self.s, self.pos) {
            Some((r, n)) => {
                self.pos += n;
                Ok(r)
            }
            None => err("invalid UTF-8"),
        }
    }

    /// The root frame is not a group, so the stack holds one frame more than the group depth.
    fn open_group(&mut self, open: String) -> Result<(), Re2Error> {
        if self.stack.len() > MAX_NESTING {
            return err("bad nesting depth");
        }
        self.stack.push(Frame::new(open));
        Ok(())
    }

    fn frame(&mut self) -> &mut Frame {
        self.stack.last_mut().expect("root frame")
    }

    fn push(&mut self, text: String, kind: PieceKind) {
        self.frame().current.push(Piece {
            text,
            kind,
            repeated: false,
            reps: Vec::new(),
        });
    }

    fn parse(mut self) -> Result<String, Re2Error> {
        let mut last_was_repeat = false;
        while self.pos < self.s.len() {
            let mut is_repeat = false;
            match self.s[self.pos] {
                b'(' => {
                    if self.peek(1) == Some(b'?') {
                        self.parse_perl_flags()?;
                    } else {
                        self.pos += 1;
                        self.open_group("(?:".to_string())?;
                    }
                }
                b'|' => {
                    self.pos += 1;
                    self.frame().finish_alternative();
                }
                b')' => {
                    self.pos += 1;
                    if self.stack.len() == 1 {
                        return err("unexpected )");
                    }
                    let mut frame = self.stack.pop().expect("checked above");
                    frame.finish_alternative();
                    let text = format!("{}{})", frame.open, frame.alternatives.join("|"));
                    self.frame().current.push(Piece {
                        text,
                        kind: PieceKind::Atom,
                        repeated: false,
                        reps: frame.reps,
                    });
                }
                b'^' => {
                    self.pos += 1;
                    self.push("^".into(), PieceKind::Assertion);
                }
                b'$' => {
                    self.pos += 1;
                    self.push("$".into(), PieceKind::Assertion);
                }
                b'.' => {
                    self.pos += 1;
                    self.push(".".into(), PieceKind::Atom);
                }
                b'[' => {
                    let text = self.parse_char_class()?;
                    self.push(text, PieceKind::Atom);
                }
                op @ (b'*' | b'+' | b'?') => {
                    self.pos += 1;
                    let mut text = (op as char).to_string();
                    if self.peek(0) == Some(b'?') {
                        self.pos += 1;
                        text.push('?');
                    }
                    if last_was_repeat {
                        return err("bad repetition operator");
                    }
                    self.apply_repeat(&text, None)?;
                    is_repeat = true;
                }
                b'{' => match self.maybe_parse_repetition() {
                    None => {
                        self.pos += 1;
                        self.push(literal('{' as u32), PieceKind::Atom);
                    }
                    Some((lo, hi)) => {
                        let mut text = match hi {
                            Some(h) if h == lo => format!("{{{lo}}}"),
                            Some(h) => format!("{{{lo},{h}}}"),
                            None => format!("{{{lo},}}"),
                        };
                        if self.peek(0) == Some(b'?') {
                            self.pos += 1;
                            text.push('?');
                        }
                        if last_was_repeat {
                            return err("bad repetition operator");
                        }
                        if hi.is_some_and(|h| h < lo)
                            || lo > MAX_REPEAT
                            || hi.unwrap_or(0) > MAX_REPEAT
                        {
                            return err("invalid repetition size");
                        }
                        self.apply_repeat(&text, Some((lo, hi)))?;
                        is_repeat = true;
                    }
                },
                b'\\' => self.parse_backslash()?,
                _ => {
                    let r = self.next_rune()?;
                    self.push(literal(r), PieceKind::Atom);
                }
            }
            last_was_repeat = is_repeat;
        }
        if self.stack.len() != 1 {
            return err("missing )");
        }
        let mut root = self.stack.pop().expect("root frame");
        root.finish_alternative();
        Ok(root.alternatives.join("|"))
    }

    fn apply_repeat(
        &mut self,
        op: &str,
        counted: Option<(u32, Option<u32>)>,
    ) -> Result<(), Re2Error> {
        let frame = self.frame();
        let Some(piece) = frame
            .current
            .iter_mut()
            .rev()
            .find(|p| p.kind != PieceKind::Flags)
        else {
            return err("missing argument to repetition operator");
        };
        if piece.repeated || piece.kind == PieceKind::Assertion {
            piece.text = format!("(?:{})", piece.text);
            piece.kind = PieceKind::Atom;
        }
        piece.text.push_str(op);
        piece.repeated = true;
        if let Some((lo, hi)) = counted {
            let divisor = hi.unwrap_or(lo);
            let children = std::mem::take(&mut piece.reps);
            let depth = 1 + children.iter().map(|c| c.depth).max().unwrap_or(0);
            if depth > MAX_NESTING {
                return err("bad nesting depth");
            }
            let node = RepNode {
                divisor,
                depth,
                children,
            };
            if (lo >= 2 || hi.unwrap_or(0) >= 2) && walk(&node, MAX_REPEAT) == 0 {
                return err("invalid repetition size");
            }
            piece.reps = vec![node];
        }
        Ok(())
    }

    /// RE2's `ParseInteger`: no leading zeros, and no value at or above 10^8 mid-parse.
    fn parse_integer(&self, at: &mut usize) -> Option<u32> {
        let s = self.s;
        if *at >= s.len() || !s[*at].is_ascii_digit() {
            return None;
        }
        if *at + 1 < s.len() && s[*at] == b'0' && s[*at + 1].is_ascii_digit() {
            return None;
        }
        let mut n: u32 = 0;
        while *at < s.len() && s[*at].is_ascii_digit() {
            if n >= 100_000_000 {
                return None;
            }
            n = n * 10 + (s[*at] - b'0') as u32;
            *at += 1;
        }
        Some(n)
    }

    /// RE2's `MaybeParseRepetition`. `None` means the `{` is a literal.
    fn maybe_parse_repetition(&mut self) -> Option<(u32, Option<u32>)> {
        let s = self.s;
        let mut at = self.pos + 1;
        let lo = self.parse_integer(&mut at)?;
        if at >= s.len() {
            return None;
        }
        let hi = if s[at] == b',' {
            at += 1;
            if at >= s.len() {
                return None;
            }
            if s[at] == b'}' {
                None
            } else {
                Some(self.parse_integer(&mut at)?)
            }
        } else {
            Some(lo)
        };
        if at >= s.len() || s[at] != b'}' {
            return None;
        }
        self.pos = at + 1;
        Some((lo, hi))
    }

    fn parse_perl_flags(&mut self) -> Result<(), Re2Error> {
        let t = self.rest();
        if (t.len() > 3 && (t[2] == b'=' || t[2] == b'!'))
            || (t.len() > 4 && t[2] == b'<' && (t[3] == b'=' || t[3] == b'!'))
        {
            return err("invalid perl operator");
        }
        if (t.len() > 4 && t[2] == b'P' && t[3] == b'<') || (t.len() > 3 && t[2] == b'<') {
            let begin = if t[2] == b'P' { 4 } else { 3 };
            let Some(end) = t[begin..]
                .iter()
                .position(|&c| c == b'>')
                .map(|p| p + begin)
            else {
                return err("invalid named capture group");
            };
            let name = std::str::from_utf8(&t[begin..end])
                .map_err(|_| Re2Error("invalid named capture group".into()))?;
            if !capture_name_regex().is_match(name.as_bytes()) {
                return err("invalid named capture group");
            }
            if !self.names.insert(name.to_string()) {
                return err("duplicate capture group name");
            }
            self.pos += end + 1;
            return self.open_group("(?:".to_string());
        }
        self.pos += 2;
        let mut negated = false;
        let mut saw_flags = false;
        // The final value of each flag the group names, in the order i, m, s, U.
        let mut set: [Option<bool>; 4] = [None; 4];
        loop {
            if self.pos >= self.s.len() {
                return err("invalid perl operator");
            }
            let c = self.next_rune()?;
            let slot = match c {
                0x69 => Some(0), // i
                0x6D => Some(1), // m
                0x73 => Some(2), // s
                0x55 => Some(3), // U
                _ => None,
            };
            if let Some(slot) = slot {
                saw_flags = true;
                set[slot] = Some(!negated);
                continue;
            }
            match c {
                0x2D => {
                    // '-'
                    if negated {
                        return err("invalid perl operator");
                    }
                    negated = true;
                    saw_flags = false;
                }
                0x3A | 0x29 => {
                    // ':' or ')'
                    if negated && !saw_flags {
                        return err("invalid perl operator");
                    }
                    let letters = ['i', 'm', 's', 'U'];
                    let on: String = (0..4)
                        .filter(|&k| set[k] == Some(true))
                        .map(|k| letters[k])
                        .collect();
                    let off: String = (0..4)
                        .filter(|&k| set[k] == Some(false))
                        .map(|k| letters[k])
                        .collect();
                    let mut flags = on;
                    if !off.is_empty() {
                        flags.push('-');
                        flags.push_str(&off);
                    }
                    if c == 0x3A {
                        self.open_group(format!("(?{flags}:"))?;
                    } else if !flags.is_empty() {
                        self.push(format!("(?{flags})"), PieceKind::Flags);
                    } else {
                        self.push(String::new(), PieceKind::Flags);
                    }
                    return Ok(());
                }
                _ => return err("invalid perl operator"),
            }
        }
    }

    fn parse_backslash(&mut self) -> Result<(), Re2Error> {
        let next = self.peek(1);
        match next {
            Some(b'b') => {
                self.pos += 2;
                self.push(r"(?-u:\b)".into(), PieceKind::Assertion);
                return Ok(());
            }
            Some(b'B') => {
                self.pos += 2;
                self.push(r"(?-u:\B)".into(), PieceKind::Assertion);
                return Ok(());
            }
            Some(b'A') => {
                self.pos += 2;
                self.push(r"\A".into(), PieceKind::Assertion);
                return Ok(());
            }
            Some(b'z') => {
                self.pos += 2;
                self.push(r"\z".into(), PieceKind::Assertion);
                return Ok(());
            }
            Some(b'C') => {
                self.pos += 2;
                self.push(r"(?s-u:.)".into(), PieceKind::Atom);
                return Ok(());
            }
            Some(b'Q') => {
                self.pos += 2;
                while self.pos < self.s.len() {
                    if self.peek(0) == Some(b'\\') && self.peek(1) == Some(b'E') {
                        self.pos += 2;
                        break;
                    }
                    let r = self.next_rune()?;
                    self.push(literal(r), PieceKind::Atom);
                }
                return Ok(());
            }
            Some(b'p' | b'P') => {
                let item = self.parse_unicode_group()?;
                let text = match item {
                    ClassItem::Nested(t) => t,
                    ClassItem::Range(..) => unreachable!("unicode groups are nested items"),
                };
                self.push(text, PieceKind::Atom);
                return Ok(());
            }
            Some(c) => {
                if let Some((negated, body)) = perl_class(c) {
                    self.pos += 2;
                    let text = format!("[{}{body}]", if negated { "^" } else { "" });
                    self.push(text, PieceKind::Atom);
                    return Ok(());
                }
            }
            None => {}
        }
        let r = self.parse_escape()?;
        self.push(literal(r), PieceKind::Atom);
        Ok(())
    }

    /// RE2's `ParseUnicodeGroup`, at `\p` or `\P`.
    fn parse_unicode_group(&mut self) -> Result<ClassItem, Re2Error> {
        let mut negated = self.peek(1) == Some(b'P');
        self.pos += 2;
        let name_bytes: &[u8] = if self.peek(0) == Some(b'{') {
            let rest = &self.s[self.pos + 1..];
            let Some(end) = rest.iter().position(|&c| c == b'}') else {
                return err("invalid character class range");
            };
            self.pos += end + 2;
            &rest[..end]
        } else {
            let start = self.pos;
            if start >= self.s.len() {
                return err("invalid character class range");
            }
            self.next_rune()?;
            &self.s[start..self.pos]
        };
        let mut name =
            std::str::from_utf8(name_bytes).map_err(|_| Re2Error("invalid UTF-8".into()))?;
        if let Some(stripped) = name.strip_prefix('^') {
            negated = !negated;
            name = stripped;
        }
        if !UNICODE_GROUPS.contains(&name) {
            return err("invalid character class range");
        }
        Ok(unicode_group_item(name, negated))
    }

    /// RE2's `ParseEscape` for a single rune.
    fn parse_escape(&mut self) -> Result<u32, Re2Error> {
        self.pos += 1;
        if self.pos >= self.s.len() {
            return err("trailing \\");
        }
        let c = self.next_rune()?;
        let is_octal = |b: Option<u8>| b.is_some_and(|b| (b'0'..=b'7').contains(&b));
        match c {
            0x30..=0x37 => {
                if c != 0x30 && !is_octal(self.peek(0)) {
                    return err("invalid escape sequence");
                }
                let mut code = c - 0x30;
                if is_octal(self.peek(0)) {
                    code = code * 8 + (self.s[self.pos] - b'0') as u32;
                    self.pos += 1;
                    if is_octal(self.peek(0)) {
                        code = code * 8 + (self.s[self.pos] - b'0') as u32;
                        self.pos += 1;
                    }
                }
                Ok(code)
            }
            0x78 => {
                // 'x'
                if self.pos >= self.s.len() {
                    return err("invalid escape sequence");
                }
                let c = self.next_rune()?;
                let hex = |r: u32| char::from_u32(r).and_then(|c| c.to_digit(16));
                if c == '{' as u32 {
                    if self.pos >= self.s.len() {
                        return err("invalid escape sequence");
                    }
                    let mut c = self.next_rune()?;
                    let mut nhex = 0;
                    let mut code: u32 = 0;
                    while let Some(d) = hex(c) {
                        nhex += 1;
                        code = code * 16 + d;
                        if code > RUNE_MAX || self.pos >= self.s.len() {
                            return err("invalid escape sequence");
                        }
                        c = self.next_rune()?;
                    }
                    if c != '}' as u32 || nhex == 0 {
                        return err("invalid escape sequence");
                    }
                    return Ok(code);
                }
                if self.pos >= self.s.len() {
                    return err("invalid escape sequence");
                }
                let c1 = self.next_rune()?;
                match (hex(c), hex(c1)) {
                    (Some(a), Some(b)) => Ok(a * 16 + b),
                    _ => err("invalid escape sequence"),
                }
            }
            0x6E => Ok(0x0A), // n
            0x72 => Ok(0x0D), // r
            0x74 => Ok(0x09), // t
            0x61 => Ok(0x07), // a
            0x66 => Ok(0x0C), // f
            0x76 => Ok(0x0B), // v
            c if c < 0x80 && !(c as u8).is_ascii_alphanumeric() => Ok(c),
            _ => err("invalid escape sequence"),
        }
    }

    /// RE2's `ParseCharClass`, at `[`.
    fn parse_char_class(&mut self) -> Result<String, Re2Error> {
        self.pos += 1;
        let mut negated = false;
        if self.peek(0) == Some(b'^') {
            self.pos += 1;
            negated = true;
        }
        let mut items: Vec<ClassItem> = Vec::new();
        let mut first = true;
        while self.pos < self.s.len() && (self.s[self.pos] != b']' || first) {
            first = false;
            let rest = self.rest();
            if rest.len() > 2 && rest[0] == b'[' && rest[1] == b':' {
                // `[:name:]` when a closing `:]` exists, else a literal `[`.
                if let Some(q) = (2..rest.len().saturating_sub(1))
                    .find(|&q| rest[q] == b':' && rest[q + 1] == b']')
                {
                    let full = &rest[2..q];
                    let (posix_negated, name) = match full.strip_prefix(b"^") {
                        Some(n) => (true, n),
                        None => (false, full),
                    };
                    let Some(body) = posix_class(name) else {
                        return err("invalid character class range");
                    };
                    self.pos += q + 2;
                    items.push(ClassItem::Nested(format!(
                        "[{}{body}]",
                        if posix_negated { "^" } else { "" }
                    )));
                    continue;
                }
            }
            if rest.len() > 2 && rest[0] == b'\\' && (rest[1] == b'p' || rest[1] == b'P') {
                items.push(self.parse_unicode_group()?);
                continue;
            }
            if rest.len() >= 2 && rest[0] == b'\\' {
                if let Some((perl_negated, body)) = perl_class(rest[1]) {
                    self.pos += 2;
                    items.push(ClassItem::Nested(format!(
                        "[{}{body}]",
                        if perl_negated { "^" } else { "" }
                    )));
                    continue;
                }
            }
            let lo = self.parse_cc_character()?;
            let rest = self.rest();
            let hi = if rest.len() >= 2 && rest[0] == b'-' && rest[1] != b']' {
                self.pos += 1;
                let hi = self.parse_cc_character()?;
                if hi < lo {
                    return err("invalid character class range");
                }
                hi
            } else {
                lo
            };
            items.push(ClassItem::Range(lo, hi));
        }
        if self.pos >= self.s.len() {
            return err("missing ]");
        }
        self.pos += 1;
        Ok(class_text(negated, &items))
    }

    fn parse_cc_character(&mut self) -> Result<u32, Re2Error> {
        if self.pos >= self.s.len() {
            return err("missing ]");
        }
        if self.s[self.pos] == b'\\' {
            return self.parse_escape();
        }
        self.next_rune()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn t(pattern: &str, input: &str) -> Option<bool> {
        Re2::new(pattern.as_bytes(), "is")
            .ok()
            .map(|r| r.test(input))
    }

    // RE2 accepts these, and the Rust nest limit rejects them; see the module doc.
    #[test]
    fn deep_nesting_fails_to_compile_without_overflow() {
        let n = 100_000;
        let repetitions = format!("(?:{}a{}){{2}}", "(?:".repeat(n), "){1}".repeat(n));
        let groups = format!("{}a{}", "(".repeat(n), ")".repeat(n));
        let stacked_flags = format!("a{}", "(?i){1}".repeat(n));
        for p in [repetitions, groups, stacked_flags] {
            assert!(Re2::new(p.as_bytes(), "").is_err());
        }
    }

    #[test]
    fn rejects_what_re2_rejects() {
        for p in [
            "(?=x)",
            "(?!x)",
            "(?<=x)",
            "(?<!x)",
            r"\1",
            r"\8",
            r"\Z",
            "a**",
            "a+*",
            "a???",
            "a{1,2}{3}",
            "a{1001}",
            "(a{100}){11}",
            "((a){10}){101}",
            "a{2,1}",
            "(?x)a",
            "(?#c)",
            "(?i-)",
            "(?-)",
            r"\e",
            r"\y",
            r"\é",
            r"\x{110000}",
            r"\p{greek}",
            r"\p{Cn}",
            "[[:foo:]]",
            "(",
            ")",
            "[",
            "[z-a]",
            "*",
            "a|*",
            "(*)",
            r"\uZZZZ",
            r"[a-\d]",
            r"\",
            "(?P<a>x)(?P<a>y)",
            "(?P<>x)",
            "(?P<a-b>x)",
        ] {
            assert_eq!(t(p, "a"), None, "{p} should fail to compile");
        }
    }

    #[test]
    fn reads_syntax_the_way_re2_does() {
        let cases: &[(&str, &str, bool)] = &[
            ("a{,5}", "a{,5}", true),
            ("{\"a\"", "{\"a\"", true),
            ("a{01}", "a{01}", true),
            (r"\<", "<", true),
            ("[a[b]]", "[]", true),
            ("[a[b]]", "a]", true),
            ("[a&&b]", "&", true),
            ("[--a]", ".", true),
            (r"\0", "\0", true),
            (r"\12", "\n", true),
            (r"\Qa.b\E", "a.b", true),
            (r"\Qa.b", "axb", false),
            (r"\p{^Greek}", "a", true),
            (r"\p{Lowercase_Letter}", "a", true),
            (r"\w", "\u{212A}", true),
            (r"\W", "\u{212A}", false),
            (r"\s", "\u{0B}", false),
            (r"\b", "é", false),
            (r"\d", "٣", false),
            ("^*", "a", true),
            ("(?<n>a)", "a", true),
            ("(?P<1a>a)", "a", true),
            (r"\C", "a", true),
            ("[]a]", "]", true),
            ("[^]a]", "b", true),
            (r"[\d-z]", "-", true),
            ("(?)", "a", true),
            ("$", "\n", true),
            ("a(?i)*", "", true),
            (r"\x{D800}", "\u{FFFD}", false),
            (r"\u{1F600}", "😀", true),
            ("(a{2}|b{500}){2}", "aaaa", true),
            ("[(?<a]", "P", true),
            (r"\cJ", "\n", true),
            (r"\p{C}", "\u{0378}", false),
        ];
        for (p, input, expected) in cases {
            assert_eq!(t(p, input), Some(*expected), "{p:?} on {input:?}");
        }
    }

    #[test]
    fn a_lone_surrogate_in_the_pattern_never_matches() {
        // WTF-8 for "a" followed by U+D83D.
        let pattern = [b'a', 0xED, 0xA0, 0xBD];
        let re = Re2::new(&pattern, "is").unwrap();
        assert!(!re.test("a\u{FFFD}"));
        let optional = [b'a', 0xED, 0xA0, 0xBD, b'?'];
        assert!(Re2::new(&optional, "is").unwrap().test("a"));
    }

    #[test]
    fn flags_change_case_and_dot() {
        assert!(Re2::new(b"^A.$", "is").unwrap().test("a\n"));
        assert!(!Re2::without_flags("^A.$").unwrap().test("a\n"));
        assert!(Re2::without_flags("(?m)^b").unwrap().test("a\nb"));
    }
}
