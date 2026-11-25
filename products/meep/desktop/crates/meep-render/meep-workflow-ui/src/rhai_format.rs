//! Lays out a workflow expression for reading. Agents tend to write Rhai as
//! dense one-liners; this only changes whitespace outside strings and
//! comments (Rhai ignores it), so the expression means exactly the same.
//!
//! Long `{ … }` blocks open onto their own lines, one statement per line;
//! long map literals put one entry per line. Short blocks stay inline.

/// A block longer than this, or holding a statement, gets its own lines.
const INLINE: usize = 56;

/// The source laid out for reading, or unchanged when it already reads well.
pub(super) fn readable(source: &str) -> String {
    if !source.lines().any(|line| line.chars().count() > 100) {
        return source.to_owned();
    }
    let chars: Vec<char> = source.chars().collect();
    let code = code_mask(&chars);
    let closing = matches(&chars, &code);
    // Which opening braces break, decided up front from their extent.
    let mut breaks = vec![false; chars.len()];
    let mut maps = vec![false; chars.len()];
    // Innermost blocks first, so a block knows whether one inside it opens.
    let mut blocks: Vec<(usize, usize)> = closing
        .iter()
        .enumerate()
        .filter_map(|(open, close)| close.map(|close| (open, close)))
        .filter(|(open, _)| chars[*open] == '{')
        .collect();
    blocks.sort_by_key(|(open, close)| close - open);
    for (open, close) in blocks {
        let map = open > 0 && chars[open - 1] == '#';
        let statement = direct(&chars, &code, &closing, open, close).any(|i| chars[i] == ';');
        let entries = direct(&chars, &code, &closing, open, close).any(|i| chars[i] == ',');
        let opened_inside = (open + 1..close).any(|i| breaks[i]);
        breaks[open] = close - open > INLINE && (statement || opened_inside || (map && entries));
        maps[open] = map;
    }
    let mut out = String::with_capacity(source.len() + source.len() / 3);
    // Closing braces of short blocks that read as `{ v }`.
    let mut padded = vec![false; chars.len()];
    // Open broken blocks: (closing index, is a map).
    let mut open: Vec<(usize, bool)> = vec![];
    let mut nesting: Vec<usize> = vec![]; // every opener, by its closing index
    let indent = |out: &mut String, level: usize| {
        while out.ends_with(' ') || out.ends_with('\t') {
            out.pop();
        }
        out.push('\n');
        out.push_str(&"    ".repeat(level));
    };
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if !code[i] {
            out.push(c);
            i += 1;
            continue;
        }
        match c {
            '\n' => {
                indent(&mut out, open.len());
                i += 1;
                while i < chars.len() && code[i] && matches!(chars[i], ' ' | '\t') {
                    i += 1;
                }
                continue;
            }
            '{' | '(' | '[' => {
                // `if x {`, `fn f(v) {`, `} else {`: a space before a block.
                if c == '{' && !maps[i] && out.chars().last().is_some_and(word_end) {
                    out.push(' ');
                }
                out.push(c);
                if let Some(close) = closing[i] {
                    nesting.push(close);
                    if c == '{' && breaks[i] {
                        open.push((close, maps[i]));
                        indent(&mut out, open.len());
                        i = skip_space(&chars, &code, i + 1);
                        continue;
                    }
                    // A short block reads as `{ v }`; an empty one stays `{}`.
                    if c == '{' && !maps[i] && close > i + 1 {
                        padded[close] = true;
                        out.push(' ');
                        i = skip_space(&chars, &code, i + 1);
                        continue;
                    }
                }
            }
            '}' | ')' | ']' => {
                nesting.pop();
                if padded[i] {
                    while out.ends_with(' ') {
                        out.pop();
                    }
                    out.push(' ');
                }
                if open.last().is_some_and(|(close, _)| *close == i) {
                    open.pop();
                    // The closing brace takes its own line, with no blank above.
                    out.truncate(out.trim_end().len());
                    indent(&mut out, open.len());
                }
                out.push(c);
                if c == '}' {
                    let next = skip_space(&chars, &code, i + 1);
                    let rest: String = chars[next.min(chars.len())..].iter().take(4).collect();
                    if rest == "else" {
                        out.push(' ');
                        i = next;
                        continue;
                    }
                }
                // Inside an opened block, a statement that follows a block
                // (`if … { … } let x = …`) starts its own line.
                if c == '}'
                    && matches!(open.last(), Some((close, false)) if nesting.last() == Some(close))
                {
                    let next = skip_space(&chars, &code, i + 1);
                    let rest: String = chars[next.min(chars.len())..].iter().take(5).collect();
                    let continues = next >= chars.len()
                        || !code[next]
                        || matches!(chars[next], '.' | ',' | ';' | ')' | ']' | '}' | '?')
                        || rest.starts_with("else")
                        || open.last().map(|(close, _)| *close) == Some(next);
                    if !continues {
                        indent(&mut out, open.len());
                        i = next;
                        continue;
                    }
                }
            }
            ';' | ',' => {
                while out.ends_with(' ') {
                    out.pop();
                }
                out.push(c);
                // `f(a, b)`: one space after a comma that isn't ending a line.
                if c == ',' && i + 1 < chars.len() && !chars[i + 1].is_whitespace() {
                    let breaking =
                        matches!(open.last(), Some((close, true)) if nesting.last() == Some(close));
                    if !breaking {
                        out.push(' ');
                    }
                }
                let direct_child = matches!(open.last(), Some((close, map))
                    if nesting.last() == Some(close) && (c == ';' || *map));
                if direct_child {
                    let next = skip_space(&chars, &code, i + 1);
                    // The block's own closing brace starts its own line anyway.
                    if next < chars.len() && open.last().map(|(c, _)| *c) != Some(next) {
                        indent(&mut out, open.len());
                        i = next;
                        continue;
                    }
                }
            }
            _ => {
                if let Some(len) = operator(&chars, &code, i) {
                    // One space either side of a binary operator.
                    while out.ends_with(' ') {
                        out.pop();
                    }
                    if !out.ends_with('\n') && !out.is_empty() {
                        out.push(' ');
                    }
                    out.extend(&chars[i..i + len]);
                    i += len;
                    while i < chars.len() && code[i] && matches!(chars[i], ' ' | '\t') {
                        i += 1;
                    }
                    if i < chars.len() && chars[i] != '\n' {
                        out.push(' ');
                    }
                    continue;
                }
                out.push(c);
                // `"key": value` inside a map literal.
                if c == ':'
                    && matches!(open.last(), Some((close, true)) if nesting.last() == Some(close))
                    && i + 1 < chars.len()
                    && !chars[i + 1].is_whitespace()
                {
                    out.push(' ');
                }
            }
        }
        i += 1;
    }
    out
}

/// Whether a block brace after this character is a statement's block
/// (`if x {`, `f(v) {`), not a map literal or an argument.
fn word_end(c: char) -> bool {
    c.is_alphanumeric() || matches!(c, ')' | ']' | '"' | '_' | '}')
}

/// The length of a binary operator starting at `i`, if one does. Unary and
/// ambiguous signs (`-`, `*`, `/`, `!`) are left exactly as written.
fn operator(chars: &[char], code: &[bool], i: usize) -> Option<usize> {
    let at = |k: usize| chars.get(k).copied().filter(|_| code.get(k) == Some(&true));
    let prev = (0..i)
        .rev()
        .map(|k| chars[k])
        .find(|c| *c != ' ' && *c != '\t');
    let binary_left = prev
        .is_some_and(|p| p.is_alphanumeric() || matches!(p, ')' | ']' | '"' | '_' | '}' | '\''));
    let pair: String = [at(i), at(i + 1)].iter().flatten().collect();
    if matches!(
        pair.as_str(),
        "==" | "!=" | "&&" | "||" | "<=" | ">=" | "+=" | "-=" | "=>"
    ) {
        // `||` also opens a closure with no parameters; only pad it between values.
        if pair == "||" && !binary_left {
            return None;
        }
        return Some(2);
    }
    match at(i)? {
        '=' if binary_left && !matches!(at(i + 1), Some('=' | '>')) => Some(1),
        '<' | '>'
            if binary_left
                && !matches!(at(i + 1), Some('<' | '>' | '='))
                && !matches!(prev, Some('<' | '>' | '-' | '=')) =>
        {
            Some(1)
        }
        '+' if binary_left && at(i + 1) != Some('+') => Some(1),
        _ => None,
    }
}

fn skip_space(chars: &[char], code: &[bool], mut i: usize) -> usize {
    while i < chars.len() && code[i] && matches!(chars[i], ' ' | '\t' | '\n' | '\r') {
        i += 1;
    }
    i
}

/// Positions directly inside `open..close`, not inside a nested bracket.
fn direct<'a>(
    chars: &'a [char],
    code: &'a [bool],
    closing: &'a [Option<usize>],
    open: usize,
    close: usize,
) -> impl Iterator<Item = usize> + 'a {
    let mut i = open + 1;
    std::iter::from_fn(move || {
        while i < close {
            let at = i;
            if code[at] && matches!(chars[at], '{' | '(' | '[') {
                i = closing[at].map_or(at + 1, |c| c + 1);
                continue;
            }
            i += 1;
            if code[at] {
                return Some(at);
            }
        }
        None
    })
}

/// For each opening bracket, the index of its closing bracket.
fn matches(chars: &[char], code: &[bool]) -> Vec<Option<usize>> {
    let mut closing = vec![None; chars.len()];
    let mut stack: Vec<usize> = vec![];
    for (i, &c) in chars.iter().enumerate() {
        if !code[i] {
            continue;
        }
        match c {
            '{' | '(' | '[' => stack.push(i),
            '}' | ')' | ']' => {
                if let Some(open) = stack.pop() {
                    closing[open] = Some(i);
                }
            }
            _ => {}
        }
    }
    closing
}

/// Whether each character is code (true) or inside a string or comment.
fn code_mask(chars: &[char]) -> Vec<bool> {
    let mut code = vec![true; chars.len()];
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        let next = chars.get(i + 1).copied();
        let end = match c {
            '"' | '`' | '\'' => {
                let mut j = i + 1;
                while j < chars.len() && chars[j] != c {
                    j += if chars[j] == '\\' && c != '`' { 2 } else { 1 };
                }
                Some(j.min(chars.len() - 1))
            }
            '/' if next == Some('/') => {
                let mut j = i;
                while j < chars.len() && chars[j] != '\n' {
                    j += 1;
                }
                Some(j.saturating_sub(1).max(i + 1))
            }
            '/' if next == Some('*') => {
                let mut j = i + 2;
                while j + 1 < chars.len() && !(chars[j] == '*' && chars[j + 1] == '/') {
                    j += 1;
                }
                Some((j + 1).min(chars.len() - 1))
            }
            _ => None,
        };
        if let Some(end) = end {
            for flag in &mut code[i..=end] {
                *flag = false;
            }
            i = end + 1;
        } else {
            i += 1;
        }
    }
    code
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Only whitespace outside strings and comments may change.
    fn same_code(a: &str, b: &str) {
        let squeeze = |s: &str| {
            let chars: Vec<char> = s.chars().collect();
            let code = code_mask(&chars);
            chars
                .iter()
                .zip(code)
                .filter(|(c, code)| !(*code && c.is_whitespace()))
                .map(|(c, _)| *c)
                .collect::<String>()
        };
        assert_eq!(squeeze(a), squeeze(b));
    }

    const DENSE: &str = r#"fn arr(v){if type_of(v)=="array"{v}else{[]}}
fn clip(v,n){let s=text(v).trimmed();if s.len()>n{take(s,n)+"…"}else{s}}
fn err(m){let s=text(m);if matches(s,"(?i)deadline|timed? ?out"){"PostHog took too long to answer; try again {soon}"}else{take(s,300)}}
fn parse_repo(v){let name=coalesce(v.n,v.nameWithOwner);if !truthy(name){return null;}let pushed=coalesce(v.p,v.pushedAt);
#{"n":name,"s":coalesce(v.s,coalesce(v.stargazerCount,0)),"f":coalesce(v.f,coalesce(v.forkCount,0)),"p":pushed,"d":text(v.description)}}
fn gh(r){if r.success!=true{let e=text(r.stderr).trimmed();if e.to_lower().contains("rate limit"){throw "GitHub rate limit; wait a minute";}throw take(e,300);}parse_json(r.stdout)} // keep { this ; comment }
fn repos(rows){let a=arr(rows).map(|r|parse_repo(r)).filter(|r|r!=null);a.sort(|a,b|if a.s!=b.s{b.s-a.s}else{0});a}
repos(gh(input.response))"#;

    #[test]
    fn dense_expressions_open_up_without_changing_their_code() {
        let laid = readable(DENSE);
        same_code(DENSE, &laid);
        assert!(laid.lines().count() > DENSE.lines().count() * 2, "{laid}");
        assert!(
            laid.contains(
                "fn gh(r) {\n    if r.success != true {\n        let e = text(r.stderr).trimmed();"
            ),
            "{laid}"
        );
        // Strings and comments are untouched, braces and semicolons included.
        assert!(laid.contains(r#""PostHog took too long to answer; try again {soon}""#));
        assert!(laid.contains("// keep { this ; comment }"));
        // Short blocks stay on their line.
        assert!(
            laid.contains(r#"if type_of(v) == "array" { v } else { [] }"#),
            "{laid}"
        );
        // A long map gets one entry per line.
        assert!(laid.contains("#{\n        \"n\": name,\n"), "{laid}");
        for line in laid.lines() {
            assert!(!line.ends_with(' '), "trailing space: {line:?}");
        }
    }

    #[test]
    fn readable_code_is_left_alone() {
        let tidy =
            "fn actionable(pr) {\n  pr.state == \"OPEN\"\n}\ninput.prs.filter(|pr| actionable(pr))";
        assert_eq!(readable(tidy), tidy);
    }

    #[test]
    fn laid_out_code_compiles_as_before() {
        // View's own workflow engine: the same parser a save goes through.
        let laid = readable(DENSE);
        meep_workflows::expressions::validate(DENSE).expect("fixture compiles");
        meep_workflows::expressions::validate(&laid).unwrap_or_else(|e| panic!("{e}\n{laid}"));
        println!("{laid}");
    }
}
