//! Remote image URLs in CSS, found with the rules of v3 `css.rs`: the `url()` and the best `image-set()` candidate in the
//! value of a property that shows an image. Custom properties and other properties do not count.

/// Calls `found` with each image URL candidate in `css`: a `style` attribute, `<style>` text or `_cssText`, which v3
/// reads the same way.
pub fn image_urls(css: &str, found: &mut impl FnMut(&str)) {
    for (start, end, collect) in declaration_value_ranges(css) {
        if collect {
            value_urls(&css[start..end], found);
        }
    }
}

pub fn declaration_image_urls(property: &str, value: &str, found: &mut impl FnMut(&str)) {
    if is_image_property(property.trim()) {
        value_urls(value, found);
    }
}

/// The value ranges of the declarations in `css`, and whether each is an image property.
fn declaration_value_ranges(css: &str) -> Vec<(usize, usize, bool)> {
    let bytes = css.as_bytes();
    let mut ranges: Vec<(usize, usize, bool)> = Vec::new();
    // Where the text of the current declaration starts, after the whitespace that leads it.
    let mut segment_start: Option<usize> = None;
    let mut brace_depth = 0usize;
    let mut paren_depth = 0usize;
    let mut bracket_depth = 0usize;
    let mut position = 0;
    while position < bytes.len() {
        if segment_start.is_none() && !bytes[position].is_ascii_whitespace() {
            segment_start = Some(position);
        }
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        if bytes[position] == b'\\' {
            position = skip_escape(bytes, position);
            continue;
        }
        if matches!(bytes[position], b'\'' | b'"') {
            position = skip_quoted(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        match bytes[position] {
            b'(' => paren_depth += 1,
            b')' => paren_depth = paren_depth.saturating_sub(1),
            b'[' => bracket_depth += 1,
            b']' => bracket_depth = bracket_depth.saturating_sub(1),
            b'{' if paren_depth == 0 && bracket_depth == 0 => {
                brace_depth += 1;
                segment_start = None;
            }
            b'}' if paren_depth == 0 && bracket_depth == 0 => {
                brace_depth = brace_depth.saturating_sub(1);
                segment_start = None;
            }
            b';' if paren_depth == 0 && bracket_depth == 0 => segment_start = None,
            // A colon in a custom property value, as in `--link: https://…`, is not a new declaration.
            b':' if paren_depth == 0
                && bracket_depth == 0
                && ranges.last().is_none_or(|previous| position >= previous.1) =>
            {
                // Each colon trims only the whitespace before it, so a long selector list stays linear.
                let property = css[segment_start.unwrap_or(position)..position].trim_end();
                let image = is_image_property(property);
                if image || property.starts_with("--") {
                    ranges.push((
                        position + 1,
                        declaration_end(bytes, position + 1, brace_depth),
                        image,
                    ));
                }
            }
            _ => {}
        }
        position += 1;
    }
    ranges
}

fn declaration_end(bytes: &[u8], start: usize, brace_depth: usize) -> usize {
    let mut position = start;
    let mut paren_depth = 0usize;
    let mut bracket_depth = 0usize;
    while position < bytes.len() {
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        if bytes[position] == b'\\' {
            position = skip_escape(bytes, position);
            continue;
        }
        if matches!(bytes[position], b'\'' | b'"') {
            position = skip_quoted(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        match bytes[position] {
            b'(' => paren_depth += 1,
            b')' => paren_depth = paren_depth.saturating_sub(1),
            b'[' => bracket_depth += 1,
            b']' => bracket_depth = bracket_depth.saturating_sub(1),
            b';' if paren_depth == 0 && bracket_depth == 0 => return position,
            b'}' if paren_depth == 0 && bracket_depth == 0 && brace_depth > 0 => return position,
            _ => {}
        }
        position += 1;
    }
    bytes.len()
}

/// The longest name [`is_image_property`] accepts, so that a longer text is not lowercased.
const MAX_IMAGE_PROPERTY_LEN: usize = "-webkit-mask-box-image-source".len();

fn is_image_property(property: &str) -> bool {
    property.len() <= MAX_IMAGE_PROPERTY_LEN
        && matches!(
            property.to_ascii_lowercase().as_str(),
            "background"
                | "background-image"
                | "border-image"
                | "border-image-source"
                | "content"
                | "cursor"
                | "list-style"
                | "list-style-image"
                | "mask"
                | "mask-border"
                | "mask-border-source"
                | "mask-image"
                | "shape-outside"
                | "symbols"
                | "-webkit-border-image"
                | "-webkit-border-image-source"
                | "-webkit-box-reflect"
                | "-webkit-mask"
                | "-webkit-mask-box-image"
                | "-webkit-mask-box-image-source"
                | "-webkit-mask-image"
        )
}

fn value_urls(value: &str, found: &mut impl FnMut(&str)) {
    let bytes = value.as_bytes();
    let mut position = 0;
    while position < bytes.len() {
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        if bytes[position] == b'\\' {
            position = skip_escape(bytes, position);
            continue;
        }
        if matches!(bytes[position], b'\'' | b'"') {
            position = skip_quoted(bytes, position).unwrap_or(bytes.len());
            continue;
        }
        let image_set = if function_at(bytes, position, b"image-set") {
            Some(b"image-set".len())
        } else if function_at(bytes, position, b"-webkit-image-set") {
            Some(b"-webkit-image-set".len())
        } else {
            None
        };
        if let Some(name_len) = image_set {
            let open = position + name_len;
            let Some(end) = matching_paren(bytes, open) else {
                return;
            };
            if let Some(source) = select_image_set_candidate(&value[open + 1..end - 1]) {
                collect(&source, found);
            }
            position = end;
            continue;
        }
        if function_at(bytes, position, b"url") {
            let (resume_at, source) = scan_url_function(value, position);
            position = resume_at;
            if let Some(source) = source {
                collect(&source, found);
            }
            continue;
        }
        position += 1;
    }
}

/// v3 collects neither a fragment nor a source with an escape in it.
fn collect(source: &str, found: &mut impl FnMut(&str)) {
    let source = source.trim();
    if !source.starts_with('#') && !source.contains('\\') {
        found(source);
    }
}

fn scan_url_function(value: &str, start: usize) -> (usize, Option<String>) {
    let bytes = value.as_bytes();
    let Some(resume_at) = matching_paren(bytes, start + 3) else {
        return (bytes.len(), None);
    };
    let contents_end = resume_at - 1;
    let mut position = start + 4;
    skip_whitespace(bytes, &mut position);
    let source = if matches!(bytes.get(position), Some(b'\'' | b'"')) {
        let content_start = position + 1;
        let Some(end) = skip_quoted(bytes, position) else {
            return (resume_at, None);
        };
        position = end;
        skip_whitespace(bytes, &mut position);
        if position != contents_end {
            return (resume_at, None);
        }
        &value[content_start..end - 1]
    } else {
        &value[position..contents_end]
    };
    let source = source.trim();
    (
        resume_at,
        (!source.is_empty() && !source.contains('\\')).then(|| source.to_owned()),
    )
}

fn select_image_set_candidate(contents: &str) -> Option<String> {
    let bytes = contents.as_bytes();
    let mut best: Option<(f64, String)> = None;
    let mut start = 0;
    let mut position = 0;
    let mut depth = 0usize;
    while position < bytes.len() {
        if bytes[position] == b'\\' {
            position = skip_escape(bytes, position);
            continue;
        }
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position)?;
            continue;
        }
        if matches!(bytes[position], b'\'' | b'"') {
            position = skip_quoted(bytes, position)?;
            continue;
        }
        match bytes[position] {
            b'(' => depth += 1,
            b')' => depth = depth.saturating_sub(1),
            b',' if depth == 0 => {
                keep_better_candidate(&mut best, &contents[start..position])?;
                start = position + 1;
            }
            _ => {}
        }
        position += 1;
    }
    keep_better_candidate(&mut best, &contents[start..])?;
    best.map(|(_, source)| source)
}

fn keep_better_candidate(best: &mut Option<(f64, String)>, candidate: &str) -> Option<()> {
    let candidate = candidate.trim();
    if candidate.is_empty() {
        return None;
    }
    let (source, remainder) = parse_image_set_source(candidate)?;
    let resolution = parse_resolution(remainder)?;
    if best
        .as_ref()
        .is_none_or(|(best_resolution, _)| resolution > *best_resolution)
    {
        *best = Some((resolution, source));
    }
    Some(())
}

fn parse_image_set_source(candidate: &str) -> Option<(String, &str)> {
    let bytes = candidate.as_bytes();
    if function_at(bytes, 0, b"url") {
        let (resume_at, source) = scan_url_function(candidate, 0);
        return Some((source?, &candidate[resume_at..]));
    }
    if matches!(bytes.first(), Some(b'\'' | b'"')) {
        let end = skip_quoted(bytes, 0)?;
        let source = candidate[1..end - 1].to_owned();
        if source.contains('\\') {
            return None;
        }
        return Some((source, &candidate[end..]));
    }
    None
}

fn parse_resolution(remainder: &str) -> Option<f64> {
    let mut resolution = None;
    for token in remainder.split_ascii_whitespace() {
        let parsed = if let Some(value) = token.strip_suffix("dppx") {
            value.parse::<f64>().ok()
        } else if let Some(value) = token.strip_suffix("dpi") {
            value.parse::<f64>().ok().map(|value| value / 96.0)
        } else if let Some(value) = token.strip_suffix("dpcm") {
            value.parse::<f64>().ok().map(|value| value * 2.54 / 96.0)
        } else if let Some(value) = token.strip_suffix('x') {
            value.parse::<f64>().ok()
        } else if token.starts_with("type(") {
            continue;
        } else {
            return None;
        };
        if resolution.replace(parsed?).is_some() {
            return None;
        }
    }
    let value = resolution.unwrap_or(1.0);
    (value.is_finite() && value > 0.0).then_some(value)
}

fn function_at(bytes: &[u8], start: usize, name: &[u8]) -> bool {
    bytes
        .get(start..start + name.len())
        .is_some_and(|candidate| candidate.eq_ignore_ascii_case(name))
        && bytes.get(start + name.len()) == Some(&b'(')
        && (start == 0
            || !matches!(bytes[start - 1], b'a'..=b'z' | b'A'..=b'Z' | b'0'..=b'9' | b'_' | b'-'))
}

fn matching_paren(bytes: &[u8], open: usize) -> Option<usize> {
    if bytes.get(open) != Some(&b'(') {
        return None;
    }
    let mut position = open + 1;
    let mut depth = 1usize;
    while position < bytes.len() {
        if starts_with(bytes, position, b"/*") {
            position = skip_comment(bytes, position)?;
            continue;
        }
        if bytes[position] == b'\\' {
            position = skip_escape(bytes, position);
            continue;
        }
        if matches!(bytes[position], b'\'' | b'"') {
            position = skip_quoted(bytes, position)?;
            continue;
        }
        match bytes[position] {
            b'(' => depth += 1,
            b')' => {
                depth -= 1;
                if depth == 0 {
                    return Some(position + 1);
                }
            }
            _ => {}
        }
        position += 1;
    }
    None
}

fn skip_quoted(bytes: &[u8], start: usize) -> Option<usize> {
    let quote = *bytes.get(start)?;
    let mut position = start + 1;
    while position < bytes.len() {
        match bytes[position] {
            b'\\' => position += 2,
            value if value == quote => return Some(position + 1),
            _ => position += 1,
        }
    }
    None
}

/// The position after the escape at `start` and the character it escapes, so that an escaped quote, bracket or
/// parenthesis does not count as one.
fn skip_escape(bytes: &[u8], start: usize) -> usize {
    let width = match bytes.get(start + 1) {
        Some(0xf0..) => 4,
        Some(0xe0..) => 3,
        Some(0xc0..) => 2,
        _ => 1,
    };
    (start + 1 + width).min(bytes.len())
}

fn skip_comment(bytes: &[u8], start: usize) -> Option<usize> {
    let relative = bytes
        .get(start + 2..)?
        .windows(2)
        .position(|pair| pair == b"*/")?;
    Some(start + 2 + relative + 2)
}

fn skip_whitespace(bytes: &[u8], position: &mut usize) {
    while bytes.get(*position).is_some_and(u8::is_ascii_whitespace) {
        *position += 1;
    }
}

fn starts_with(bytes: &[u8], start: usize, needle: &[u8]) -> bool {
    bytes.get(start..start + needle.len()) == Some(needle)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_past_escapes_outside_strings() {
        // Tailwind escapes brackets, parentheses and quotes in its arbitrary value class names.
        let css = r".bg-\[url\(\'\/hero\.png\'\)\]{background-image:url('/hero.png')}.a{background:url(https://cdn.example.com/a.png)}";
        let mut found = Vec::new();
        image_urls(css, &mut |url| found.push(url.to_owned()));
        assert_eq!(found, ["/hero.png", "https://cdn.example.com/a.png"]);
    }

    #[test]
    fn scans_a_long_selector_list_in_linear_time() {
        let css = format!(
            "{} a:hover {{ background: url(https://cdn.example.com/a.png) }}",
            "a:hover, b:focus-visible,\n".repeat(50_000)
        );
        let mut found = Vec::new();
        image_urls(&css, &mut |url| found.push(url.to_owned()));
        assert_eq!(found, ["https://cdn.example.com/a.png"]);
    }
}
