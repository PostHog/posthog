use std::sync::atomic::Ordering;

use serde::Serialize;
use sourcemap::Token;
use symbolic::sourcemapcache::SourceLocation;

use crate::{
    config::FRAME_CONTEXT_LINES,
    frames::{Context, ContextLine, Frame},
};

pub fn add_raw_to_junk<T: Serialize + Clone>(frame: &mut Frame, raw: &T) {
    // UNWRAP: raw JS frames are definitely representable as json
    frame.add_junk("raw_frame", raw.clone()).unwrap();
}

pub fn get_sourcelocation_context(token: &SourceLocation) -> Option<Context> {
    let file = token.file()?;
    let token_line_num = token.line();
    let src = file.source()?;

    let line_limit = FRAME_CONTEXT_LINES.load(Ordering::Relaxed);
    get_context_lines(src.lines(), token_line_num as usize, line_limit)
}

pub fn get_token_context(token: &Token<'_>, line: usize) -> Option<Context> {
    let src = token.get_source_view()?;
    let lines = src.lines();

    let line_limit = FRAME_CONTEXT_LINES.load(Ordering::Relaxed);
    get_context_lines(lines, line, line_limit)
}

fn get_context_lines<'a, L>(lines: L, line: usize, context_len: usize) -> Option<Context>
where
    L: Iterator<Item = &'a str>,
{
    let start = line.saturating_sub(context_len).saturating_sub(1);

    let mut lines = lines.enumerate().skip(start);
    let before = (&mut lines)
        .take(line - start)
        .map(|(number, line)| ContextLine::new(number as u32, line))
        .collect();

    let line = lines
        .next()
        .map(|(number, line)| ContextLine::new(number as u32, line))?;

    let after = lines
        .take(context_len)
        .map(|(number, line)| ContextLine::new(number as u32, line))
        .collect();

    Some(Context {
        before,
        line,
        after,
    })
}
