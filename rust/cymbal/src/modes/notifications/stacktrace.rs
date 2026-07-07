use crate::frames::Frame;
use crate::tokenizer::CL100K_BPE;
use crate::types::OutputErrProps;

/// Render exception types, messages, and stack frames as a human-readable string.
///
/// If `max_tokens` is `Some(limit)`, the output is measured against `limit`
/// tokens (using the cl100k_base tiktoken encoding). When the full output
/// would exceed the limit, only the first and last frame of each exception
/// are kept with a `...` marker between them. If the truncated output is
/// still over the limit, the string is hard-truncated to exactly `limit`
/// tokens.
pub fn print_stacktrace(props: &OutputErrProps, max_tokens: Option<usize>) -> String {
    let full = render_stacktrace(props, false);

    let Some(limit) = max_tokens else {
        return full;
    };

    let bpe = &*CL100K_BPE;
    let tokens = bpe.encode_with_special_tokens(&full);

    if tokens.len() <= limit {
        return full;
    }

    let truncated = render_stacktrace(props, true);
    let tokens = bpe.encode_with_special_tokens(&truncated);

    if tokens.len() <= limit {
        return truncated;
    }

    let mut tokens: Vec<_> = tokens.into_iter().take(limit).collect();
    loop {
        match bpe.decode(tokens.clone()) {
            Ok(text) => break text,
            Err(_) => {
                tokens.pop();
            }
        }
    }
}

fn render_stacktrace(props: &OutputErrProps, truncate: bool) -> String {
    let mut content = String::with_capacity(2048);

    for exception in &props.exception_list.0 {
        let type_and_value = format!(
            "{}: {}\n",
            exception.exception_type,
            exception
                .exception_message
                .chars()
                .take(300)
                .collect::<String>()
        );

        content.push_str(&type_and_value);

        let Some(stack) = &exception.stack else {
            continue;
        };

        let frames = stack.get_frames();

        if truncate && frames.len() > 2 {
            content.push_str(&render_frame(&frames[0]));
            content.push_str("...\n");
            content.push_str(&render_frame(frames.last().unwrap()));
        } else {
            for frame in frames {
                content.push_str(&render_frame(frame));
            }
        }
    }

    content
}

fn render_frame(frame: &Frame) -> String {
    let mut output = String::new();

    if let Some(resolved_name) = &frame.resolved_name {
        output.push_str(resolved_name);
    } else {
        output.push_str(&frame.mangled_name);
    }

    if let Some(source) = &frame.source {
        output.push_str(&format!(" in {source}"));
    }

    if let Some(line) = frame.line {
        output.push_str(&format!(" line {line}"));
    }

    if let Some(column) = frame.column {
        output.push_str(&format!(" column {column}"));
    }

    output.push('\n');
    output
}
