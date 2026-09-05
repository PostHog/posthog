use serde::Serialize;
use sourcemap::Token;
use symbolic::sourcemapcache::SourceLocation;

use crate::frames::{Context, ContextLine, Frame};

pub fn add_raw_to_junk<T: Serialize + Clone>(frame: &mut Frame, raw: &T) {
    // UNWRAP: raw JS frames are definitely representable as json
    frame.add_junk("raw_frame", raw.clone()).unwrap();
}

pub fn get_sourcelocation_context(token: &SourceLocation, context_lines: usize) -> Option<Context> {
    let file = token.file()?;
    let token_line_num = token.line();
    let src = file.source()?;

    get_context_lines(src.lines(), token_line_num as usize, context_lines)
}

pub fn is_kotlin_compose_source(source: &str) -> bool {
    let normalized = source.replace('\\', "/");
    normalized.contains("/kotlin/androidx/compose/")
        || normalized.contains("/kotlin/org/jetbrains/compose/")
}

// Browser extensions inject scripts under their own URL schemes. Safari masks such scripts as
// `webkit-masked-url://hidden/`, and Chrome and Firefox use `chrome-extension://` and
// `moz-extension://`. Frames from these sources are not the page's own code, so we must not
// mark them `in_app`.
pub fn is_extension_source(source: &str) -> bool {
    const EXTENSION_SCHEMES: [&str; 3] = [
        "webkit-masked-url://",
        "chrome-extension://",
        "moz-extension://",
    ];
    EXTENSION_SCHEMES
        .iter()
        .any(|scheme| source.starts_with(scheme))
}

pub fn get_token_context(token: &Token<'_>, line: usize, context_lines: usize) -> Option<Context> {
    let src = token.get_source_view()?;
    let lines = src.lines();

    get_context_lines(lines, line, context_lines)
}

pub fn get_context_lines<'a, L>(lines: L, line: usize, context_len: usize) -> Option<Context>
where
    L: Iterator<Item = &'a str>,
{
    let start = line.saturating_sub(context_len).saturating_sub(1);

    let mut lines = lines.enumerate().skip(start);
    // enumerate() is 0-based but line numbers displayed in the UI should be 1-based
    let before = (&mut lines)
        .take(line - start)
        .map(|(number, line)| ContextLine::new(number as u32 + 1, line))
        .collect();

    let line = lines
        .next()
        .map(|(number, line)| ContextLine::new(number as u32 + 1, line))?;

    let after = lines
        .take(context_len)
        .map(|(number, line)| ContextLine::new(number as u32 + 1, line))
        .collect();

    Some(Context {
        before,
        line,
        after,
    })
}
