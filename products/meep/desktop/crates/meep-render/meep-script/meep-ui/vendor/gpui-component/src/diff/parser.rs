use std::{fmt, ops::Range};

use gpui::SharedString;

use super::document::{DiffFile, DiffFileStatus, FileSide, Hunk, LinePair};

/// A malformed or unsupported unified diff, with its one-based patch line.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DiffParseError {
    line: usize,
    message: SharedString,
}

impl DiffParseError {
    pub fn line(&self) -> usize {
        self.line
    }
    pub fn message(&self) -> &SharedString {
        &self.message
    }
    pub(crate) fn new(line: usize, message: &'static str) -> Self {
        Self {
            line,
            message: SharedString::new_static(message),
        }
    }
}
impl fmt::Display for DiffParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "patch line {}: {}", self.line, self.message)
    }
}
impl std::error::Error for DiffParseError {}

type Result<T> = std::result::Result<T, DiffParseError>;

/// Relaxations for [`DiffFile::parse_with`]. Every relaxation is off by
/// default, which parses exactly as [`DiffFile::parse`] does.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct DiffParseOptions {
    truncated_hunks: bool,
}

impl DiffParseOptions {
    pub fn new() -> Self {
        Self::default()
    }

    /// Accept hunks that end before their declared line counts, as in a patch
    /// cut at a size limit, and count each from the lines present. Declared
    /// counts still bound a hunk, so a line beyond them remains an error.
    pub fn truncated_hunks(mut self, truncated_hunks: bool) -> Self {
        self.truncated_hunks = truncated_hunks;
        self
    }

    pub fn has_truncated_hunks(&self) -> bool {
        self.truncated_hunks
    }
}

/// Source prefixes Git writes on each side: the default `a/` and `b/`, the
/// `diff.mnemonicPrefix` pairs, `--no-index` and `diff.noprefix`.
const GIT_PREFIXES: [(&str, &str); 7] = [
    ("a/", "b/"),
    ("i/", "w/"),
    ("c/", "w/"),
    ("c/", "i/"),
    ("o/", "w/"),
    ("1/", "2/"),
    ("", ""),
];

/// One file side while parsing: patch source is appended once, and lines are
/// recorded as ranges until the file is complete.
#[derive(Default)]
struct SideBuilder {
    source: String,
    lines: Vec<(usize, Range<usize>)>,
    no_newline: bool,
}

impl SideBuilder {
    fn push(&mut self, line_number: usize, content: &str) -> usize {
        let start = self.source.len();
        self.source.push_str(content);
        self.source.push('\n');
        self.lines.push((line_number, start..self.source.len()));
        self.lines.len() - 1
    }
    fn remove_final_newline(&mut self) {
        if let Some((_, range)) = self.lines.last_mut() {
            self.source.pop();
            range.end -= 1;
        }
        self.no_newline = true;
    }
    fn finish(self, path: Option<String>) -> FileSide {
        FileSide::new(path.map(SharedString::from), self.source, self.lines)
    }
}

#[derive(Default)]
struct File {
    old_path: Option<String>,
    new_path: Option<String>,
    /// Prefixes detected from `diff --git`, stripped from `---` and `+++` paths.
    git_prefixes: Option<(&'static str, &'static str)>,
    original: SideBuilder,
    modified: SideBuilder,
    pairs: Vec<LinePair>,
    hunks: Vec<Hunk>,
    /// Empty truncated hunks still constrain the next hunk's position.
    last_hunk_start: Option<(usize, usize)>,
    extended_headers: Vec<SharedString>,
    binary: bool,
    headers: bool,
    renamed: bool,
    copied: bool,
}

impl File {
    fn finish(self) -> DiffFile {
        let status = if self.old_path.is_none() {
            DiffFileStatus::Added
        } else if self.new_path.is_none() {
            DiffFileStatus::Deleted
        } else if self.copied {
            DiffFileStatus::Copied
        } else if self.renamed {
            DiffFileStatus::Renamed
        } else {
            DiffFileStatus::Modified
        };
        DiffFile::new(
            status,
            self.original.finish(self.old_path),
            self.modified.finish(self.new_path),
            self.pairs,
            self.hunks,
            self.extended_headers,
            self.binary,
        )
    }

    fn flush_changes(&mut self, deleted: &mut Vec<usize>, added: &mut Vec<usize>) {
        for ix in 0..deleted.len().max(added.len()) {
            self.pairs.push(LinePair::new(
                deleted.get(ix).copied(),
                added.get(ix).copied(),
                true,
            ));
        }
        deleted.clear();
        added.clear();
    }
}

pub(crate) fn parse(patch: &str, options: DiffParseOptions) -> Result<Vec<DiffFile>> {
    let raw: Vec<&str> = patch
        .split_inclusive('\n')
        .map(|line| line.strip_suffix('\n').unwrap_or(line))
        .collect();
    // Git preserves CR in source lines but emits LF headers. CRLF transport
    // instead has CR on its header records as well; strip that framing CR only.
    let transport_crlf = raw
        .iter()
        .find(|line| line.starts_with("diff --git ") || line.starts_with("--- "))
        .is_some_and(|line| line.ends_with('\r'));
    let lines: Vec<&str> = raw
        .iter()
        .map(|line| {
            if transport_crlf {
                line.strip_suffix('\r').unwrap_or(line)
            } else {
                line
            }
        })
        .collect();
    let mut files = Vec::new();
    let mut current: Option<File> = None;
    let mut ix = 0;
    while ix < lines.len() {
        let line = lines[ix];
        if line.starts_with("diff --cc ")
            || line.starts_with("diff --combined ")
            || line.starts_with("@@@")
        {
            return Err(DiffParseError::new(
                ix + 1,
                "combined diffs are not supported",
            ));
        }
        if let Some(paths) = line.strip_prefix("diff --git ") {
            if let Some(file) = current.take() {
                files.push(file.finish());
            }
            let (old, new, prefixes) = git_paths(paths)
                .ok_or_else(|| DiffParseError::new(ix + 1, "invalid Git file header"))?;
            current = Some(File {
                old_path: Some(old),
                new_path: Some(new),
                git_prefixes: Some(prefixes),
                ..File::default()
            });
            ix += 1;
            continue;
        }
        // `git format-patch` ends each message with a `-- ` signature line,
        // followed by the Git version. Mail clients may strip its trailing space.
        if line == "-- " || line == "--" {
            if let Some(file) = current.take() {
                files.push(file.finish());
            }
            ix += 1;
            continue;
        }
        if let Some(path) = line.strip_prefix("--- ") {
            if current.as_ref().is_some_and(|file| file.headers) {
                files.push(current.take().unwrap().finish());
            }
            let file = current.get_or_insert_with(File::default);
            let old = header_path(path, ix + 1)?;
            ix += 1;
            let Some(path) = lines.get(ix).and_then(|line| line.strip_prefix("+++ ")) else {
                return Err(DiffParseError::new(ix + 1, "expected modified file header"));
            };
            let new = header_path(path, ix + 1)?;
            if old.is_none() && new.is_none() {
                return Err(DiffParseError::new(ix + 1, "both file sides are missing"));
            }
            let (old_prefix, new_prefix) = file.git_prefixes.unwrap_or_else(|| {
                // Without a Git header, strip `a/` and `b/` only when the
                // present sides agree on that convention.
                let conventional = old.as_deref().is_none_or(|path| path.starts_with("a/"))
                    && new.as_deref().is_none_or(|path| path.starts_with("b/"));
                if conventional { ("a/", "b/") } else { ("", "") }
            });
            file.old_path = old.map(|path| strip_prefix(path, old_prefix));
            file.new_path = new.map(|path| strip_prefix(path, new_prefix));
            file.headers = true;
            ix += 1;
            continue;
        }
        if line.starts_with("@@ ") {
            let file = current
                .as_mut()
                .ok_or_else(|| DiffParseError::new(ix + 1, "hunk has no file header"))?;
            if !file.headers {
                return Err(DiffParseError::new(
                    ix + 1,
                    "hunk requires original and modified file headers",
                ));
            }
            ix = parse_hunk(file, &lines, ix, options)?;
            continue;
        }
        // Binary payload is opaque to the UI. Keep its marker, not thousands
        // of encoded records or a fabricated text source.
        if current.as_ref().is_some_and(|file| file.binary) {
            ix += 1;
            continue;
        }
        if (line.starts_with('+')
            || line.starts_with('-')
            || line.starts_with(' ')
            || line.starts_with("\\ No newline"))
            && current.as_ref().is_some_and(|file| file.headers)
        {
            return Err(DiffParseError::new(ix + 1, "source line outside a hunk"));
        }
        if let Some(file) = &mut current {
            if line.starts_with("Binary files ") || line == "GIT binary patch" {
                file.binary = true;
            }
            if let Some(path) = line.strip_prefix("rename from ") {
                file.old_path = Some(decode_path(path, ix + 1)?);
                file.renamed = true;
            }
            if let Some(path) = line.strip_prefix("copy from ") {
                file.old_path = Some(decode_path(path, ix + 1)?);
                file.copied = true;
            }
            if let Some(path) = line
                .strip_prefix("rename to ")
                .or_else(|| line.strip_prefix("copy to "))
            {
                file.new_path = Some(decode_path(path, ix + 1)?);
            }
            if line.starts_with("new file mode ") {
                file.old_path = None;
            }
            if line.starts_with("deleted file mode ") {
                file.new_path = None;
            }
            if !line.is_empty() {
                file.extended_headers.push(line.to_owned().into());
            }
        }
        ix += 1;
    }
    if let Some(file) = current {
        files.push(file.finish());
    }
    if files.is_empty() && !patch.trim().is_empty() {
        return Err(DiffParseError::new(1, "expected a unified or Git diff"));
    }
    Ok(files)
}

/// Parses the hunk whose header is `lines[ix]` and returns the next line index.
fn parse_hunk(
    file: &mut File,
    lines: &[&str],
    mut ix: usize,
    options: DiffParseOptions,
) -> Result<usize> {
    let header = lines[ix];
    let (old_start, old_count, new_start, new_count) = hunk_header(header, ix + 1)?;
    // A zero-count side names the line before its insertion point.
    let first_original = old_start + usize::from(old_count == 0);
    let first_modified = new_start + usize::from(new_count == 0);
    let last_line = |side: &SideBuilder| side.lines.last().map(|(number, _)| *number);
    if options.truncated_hunks
        && file
            .last_hunk_start
            .is_some_and(|(old, new)| first_original < old || first_modified < new)
        || last_line(&file.original).is_some_and(|number| number >= old_start) && old_count > 0
        || last_line(&file.modified).is_some_and(|number| number >= new_start) && new_count > 0
    {
        return Err(DiffParseError::new(
            ix + 1,
            "overlapping or unordered hunks",
        ));
    }
    if file.old_path.is_none() && old_count != 0 || file.new_path.is_none() && new_count != 0 {
        return Err(DiffParseError::new(
            ix + 1,
            "missing file side has source lines",
        ));
    }
    let pairs_start = file.pairs.len();
    let original_start = file.original.lines.len();
    let modified_start = file.modified.lines.len();
    ix += 1;
    let next_file = if options.truncated_hunks {
        truncated_file_header(lines, ix, old_count, new_count)
    } else {
        None
    };
    let (mut old_used, mut new_used) = (0, 0);
    let (mut deleted, mut added) = (Vec::new(), Vec::new());
    let mut last = None;
    while ix < lines.len() {
        if Some(ix) == next_file {
            break;
        }
        let content = lines[ix];
        if content == "\\ No newline at end of file" {
            match last {
                Some(b'-') => file.original.remove_final_newline(),
                Some(b'+') => file.modified.remove_final_newline(),
                Some(b' ') => {
                    file.original.remove_final_newline();
                    file.modified.remove_final_newline();
                }
                _ => {
                    return Err(DiffParseError::new(
                        ix + 1,
                        "newline marker has no preceding source line",
                    ));
                }
            }
            last = None;
            ix += 1;
            continue;
        }
        if old_used == old_count && new_used == new_count {
            break;
        }
        // Editors and mail transports may strip the space from an empty
        // context line; `git apply` accepts that, so accept it here too.
        let tag = content.as_bytes().first().copied().unwrap_or(b' ');
        if !matches!(tag, b' ' | b'+' | b'-') {
            if options.truncated_hunks {
                break;
            }
            return Err(DiffParseError::new(
                ix + 1,
                "hunk ended before its declared line counts",
            ));
        }
        let text = content.get(1..).unwrap_or_default();
        if tag != b'+' && file.original.no_newline || tag != b'-' && file.modified.no_newline {
            return Err(DiffParseError::new(
                ix + 1,
                "source continues after an unterminated final line",
            ));
        }
        match tag {
            b' ' => {
                file.flush_changes(&mut deleted, &mut added);
                if old_used >= old_count || new_used >= new_count {
                    return Err(DiffParseError::new(
                        ix + 1,
                        "hunk exceeds declared line counts",
                    ));
                }
                let original = file.original.push(old_start + old_used, text);
                let modified = file.modified.push(new_start + new_used, text);
                file.pairs
                    .push(LinePair::new(Some(original), Some(modified), false));
                old_used += 1;
                new_used += 1;
            }
            b'-' => {
                if old_used >= old_count {
                    return Err(DiffParseError::new(
                        ix + 1,
                        "hunk exceeds original line count",
                    ));
                }
                deleted.push(file.original.push(old_start + old_used, text));
                old_used += 1;
            }
            _ => {
                if new_used >= new_count {
                    return Err(DiffParseError::new(
                        ix + 1,
                        "hunk exceeds modified line count",
                    ));
                }
                added.push(file.modified.push(new_start + new_used, text));
                new_used += 1;
            }
        }
        last = Some(tag);
        ix += 1;
    }
    let truncated = old_used != old_count || new_used != new_count;
    if truncated && !options.truncated_hunks {
        return Err(DiffParseError::new(
            ix + 1,
            "hunk ended before its declared line counts",
        ));
    }
    file.flush_changes(&mut deleted, &mut added);
    file.hunks.push(Hunk::new(
        pairs_start..file.pairs.len(),
        original_start..file.original.lines.len(),
        modified_start..file.modified.lines.len(),
        header.to_owned().into(),
        first_original..first_original + old_used,
        truncated,
    ));
    file.last_hunk_start = Some((first_original, first_modified));
    Ok(ix)
}

/// Finds a unified file header inside a short hunk. A header-looking pair
/// can also be source text, so a complete hunk interpretation wins. Scan
/// once before parsing rather than looking ahead again at every such pair.
fn truncated_file_header(
    lines: &[&str],
    start: usize,
    mut old_remaining: usize,
    mut new_remaining: usize,
) -> Option<usize> {
    let mut header = None;
    for ix in start..lines.len() {
        let line = lines[ix];
        if line == "\\ No newline at end of file" {
            continue;
        }
        if old_remaining == 0 && new_remaining == 0 {
            return None;
        }
        if header.is_none()
            && line.starts_with("--- ")
            && lines
                .get(ix + 1)
                .is_some_and(|line| line.starts_with("+++ "))
        {
            header = Some(ix);
        }
        match line.as_bytes().first().copied().unwrap_or(b' ') {
            b' ' if old_remaining > 0 && new_remaining > 0 => {
                old_remaining -= 1;
                new_remaining -= 1;
            }
            b'-' if old_remaining > 0 => old_remaining -= 1,
            b'+' if new_remaining > 0 => new_remaining -= 1,
            _ => return header,
        }
    }
    if old_remaining == 0 && new_remaining == 0 {
        None
    } else {
        header
    }
}

fn hunk_header(line: &str, number: usize) -> Result<(usize, usize, usize, usize)> {
    let invalid = || DiffParseError::new(number, "invalid hunk header");
    let body = line.strip_prefix("@@ ").ok_or_else(invalid)?;
    let (ranges, _) = body.split_once(" @@").ok_or_else(invalid)?;
    let mut fields = ranges.split_whitespace();
    let old = fields
        .next()
        .and_then(|value| value.strip_prefix('-'))
        .ok_or_else(invalid)?;
    let new = fields
        .next()
        .and_then(|value| value.strip_prefix('+'))
        .ok_or_else(invalid)?;
    if fields.next().is_some() {
        return Err(invalid());
    }
    fn range(value: &str) -> Option<(usize, usize)> {
        let (start, count) = value.split_once(',').unwrap_or((value, "1"));
        let start = start.parse::<usize>().ok()?;
        let count = count.parse::<usize>().ok()?;
        if count > 0 && start == 0 || start.checked_add(count.max(1)).is_none() {
            return None;
        }
        Some((start, count))
    }
    let (old_start, old_count) = range(old).ok_or_else(invalid)?;
    let (new_start, new_count) = range(new).ok_or_else(invalid)?;
    Ok((old_start, old_count, new_start, new_count))
}

fn strip_prefix(path: String, prefix: &str) -> String {
    match path.strip_prefix(prefix) {
        Some(stripped) if !prefix.is_empty() => stripped.to_owned(),
        _ => path,
    }
}

/// Decodes a `---` or `+++` path, or `None` for `/dev/null`.
fn header_path(value: &str, number: usize) -> Result<Option<String>> {
    let value = value.split('\t').next().unwrap_or(value);
    if value == "/dev/null" {
        Ok(None)
    } else {
        decode_path(value, number).map(Some)
    }
}

/// Splits the paths of a `diff --git` header and detects their prefixes.
fn git_paths(value: &str) -> Option<(String, String, (&'static str, &'static str))> {
    let detect = |old: &str, new: &str| {
        GIT_PREFIXES
            .iter()
            .copied()
            .find(|(old_prefix, new_prefix)| {
                old.starts_with(old_prefix) && new.starts_with(new_prefix)
            })
            .unwrap_or(("", ""))
    };
    let (old, new, prefixes) =
        if value.starts_with('"') {
            let end = quoted_end(value)?;
            let old = decode_path(&value[..end], 1).ok()?;
            let new = decode_path(value[end..].trim_start(), 1).ok()?;
            let prefixes = detect(&old, &new);
            (old, new, prefixes)
        } else if value.ends_with('"') {
            let start = value
                .match_indices(" \"")
                .map(|(ix, _)| ix + 1)
                .find(|ix| quoted_end(&value[*ix..]) == Some(value.len() - ix))?;
            let old = value[..start - 1].to_owned();
            let new = decode_path(&value[start..], 1).ok()?;
            let prefixes = detect(&old, &new);
            (old, new, prefixes)
        } else {
            // Git does not quote spaces. Without a rename both sides name the
            // same path, which identifies the separating space unambiguously.
            let same =
                GIT_PREFIXES.iter().find_map(|&(old_prefix, new_prefix)| {
                    value.match_indices(' ').find_map(|(ix, _)| {
                        let (old, new) = (&value[..ix], &value[ix + 1..]);
                        let path = old.strip_prefix(old_prefix)?;
                        (!path.is_empty() && new.strip_prefix(new_prefix) == Some(path))
                            .then_some((old, new, (old_prefix, new_prefix)))
                    })
                });
            // Otherwise this is a rename or copy, and `rename from`/`rename to`
            // records supply the exact paths.
            let (old, new, prefixes) = same
                .or_else(|| {
                    GIT_PREFIXES
                        .iter()
                        .filter(|(old_prefix, _)| !old_prefix.is_empty())
                        .find_map(|&(old_prefix, new_prefix)| {
                            let ix = value.rfind(&format!(" {new_prefix}"))?;
                            value.starts_with(old_prefix).then_some((
                                &value[..ix],
                                &value[ix + 1..],
                                (old_prefix, new_prefix),
                            ))
                        })
                })
                .or_else(|| {
                    let (old, new) = value.split_once(' ')?;
                    Some((old, new, ("", "")))
                })?;
            (old.to_owned(), new.to_owned(), prefixes)
        };
    Some((
        strip_prefix(old, prefixes.0),
        strip_prefix(new, prefixes.1),
        prefixes,
    ))
}

fn quoted_end(value: &str) -> Option<usize> {
    let mut escaped = false;
    for (ix, character) in value.char_indices().skip(1) {
        if escaped {
            escaped = false;
            continue;
        }
        if character == '\\' {
            escaped = true;
        } else if character == '"' {
            return Some(ix + 1);
        }
    }
    None
}

fn decode_path(value: &str, number: usize) -> Result<String> {
    if !value.starts_with('"') {
        return Ok(value.to_owned());
    }
    if quoted_end(value) != Some(value.len()) {
        return Err(DiffParseError::new(number, "invalid quoted file path"));
    }
    let mut output = Vec::new();
    let bytes = &value.as_bytes()[1..value.len() - 1];
    let mut ix = 0;
    while ix < bytes.len() {
        if bytes[ix] != b'\\' {
            output.push(bytes[ix]);
            ix += 1;
            continue;
        }
        ix += 1;
        let Some(&escaped) = bytes.get(ix) else {
            return Err(DiffParseError::new(number, "invalid path escape"));
        };
        match escaped {
            b'0'..=b'7' => {
                let mut byte = 0u16;
                let mut count = 0;
                while count < 3
                    && bytes
                        .get(ix)
                        .is_some_and(|byte| (b'0'..=b'7').contains(byte))
                {
                    byte = byte * 8 + u16::from(bytes[ix] - b'0');
                    ix += 1;
                    count += 1;
                }
                if byte > 255 {
                    return Err(DiffParseError::new(number, "invalid octal path escape"));
                }
                output.push(byte as u8);
            }
            b'n' => {
                output.push(b'\n');
                ix += 1;
            }
            b't' => {
                output.push(b'\t');
                ix += 1;
            }
            b'r' => {
                output.push(b'\r');
                ix += 1;
            }
            b'a' | b'b' | b'f' | b'v' => {
                output.push(match escaped {
                    b'a' => 7,
                    b'b' => 8,
                    b'f' => 12,
                    _ => 11,
                });
                ix += 1;
            }
            b'"' | b'\\' => {
                output.push(escaped);
                ix += 1;
            }
            _ => return Err(DiffParseError::new(number, "unsupported path escape")),
        }
    }
    String::from_utf8(output)
        .map_err(|_| DiffParseError::new(number, "file path is not valid UTF-8"))
}
