use std::ops::Range;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum CharType {
    /// a-z, A-Z, 0-9, _
    Word,
    /// '\t', ' ', '\u{00A0}' etc.
    Whitespace,
    /// \n, \r
    Newline,
    /// . , ; : ( ) [ ] { } ... or CJK characters: `汉`, `🎉` etc.
    Other,
}

/// Implementation based on <https://github.com/zed-industries/zed/blob/main/crates/gpui/src/text_system/line_wrapper.rs>
fn is_word_char(c: char) -> bool {
    matches!(c, '_')
        // ASCII alphanumeric characters, for English, numbers: `Hello123`, etc.
        || c.is_ascii_alphanumeric()
        // Latin script in Unicode for French, German, Spanish, etc.
        || matches!(c, '\u{00C0}'..='\u{00FF}')
        || matches!(c, '\u{0100}'..='\u{017F}')
        || matches!(c, '\u{0180}'..='\u{024F}')
        // Cyrillic for Russian, Ukrainian, etc.
        || matches!(c, '\u{0400}'..='\u{04FF}')
        // Vietnamese
        || matches!(c, '\u{1E00}'..='\u{1EFF}')
        || matches!(c, '\u{0300}'..='\u{036F}')
}

impl From<char> for CharType {
    fn from(c: char) -> Self {
        match c {
            c if is_word_char(c) => CharType::Word,
            c if c == '\n' || c == '\r' => CharType::Newline,
            c if c.is_whitespace() => CharType::Whitespace,
            _ => CharType::Other,
        }
    }
}

impl CharType {
    fn is_connectable(self, c: char) -> bool {
        matches!(
            (self, CharType::from(c)),
            (CharType::Word, CharType::Word) | (CharType::Whitespace, CharType::Whitespace)
        )
    }
}

pub(crate) fn word_range_from_chars(
    offset: usize,
    c: char,
    prev_chars: impl Iterator<Item = char>,
    next_chars: impl Iterator<Item = char>,
) -> Range<usize> {
    let char_type = CharType::from(c);
    let mut start = offset;
    let mut end = offset + c.len_utf8();

    for prev in prev_chars.take(128) {
        if char_type.is_connectable(prev) {
            start -= prev.len_utf8();
        } else {
            break;
        }
    }

    for next in next_chars.take(128) {
        if char_type.is_connectable(next) {
            end += next.len_utf8();
        } else {
            break;
        }
    }

    start..end
}

pub(crate) fn word_range_at(text: &str, offset: usize) -> Option<Range<usize>> {
    if text.is_empty() {
        return None;
    }

    let offset = clip_offset(text, offset);
    let c = text[offset..].chars().next()?;
    Some(word_range_from_chars(
        offset,
        c,
        text[..offset].chars().rev(),
        text[offset + c.len_utf8()..].chars(),
    ))
}

fn clip_offset(text: &str, offset: usize) -> usize {
    let offset = offset.min(text.len());
    if offset == text.len() {
        return text.char_indices().next_back().map_or(0, |(ix, _)| ix);
    }

    if text.is_char_boundary(offset) {
        offset
    } else {
        text.char_indices()
            .map(|(ix, _)| ix)
            .take_while(|ix| *ix < offset)
            .last()
            .unwrap_or_default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_char_type_from_char() {
        assert_eq!(CharType::from('a'), CharType::Word);
        assert_eq!(CharType::from('Z'), CharType::Word);
        assert_eq!(CharType::from('0'), CharType::Word);
        assert_eq!(CharType::from('_'), CharType::Word);
        assert_eq!(CharType::from('.'), CharType::Other);
        assert_eq!(CharType::from(','), CharType::Other);
        assert_eq!(CharType::from(';'), CharType::Other);
        assert_eq!(CharType::from('!'), CharType::Other);
        assert_eq!(CharType::from('?'), CharType::Other);
        assert_eq!(CharType::from('['), CharType::Other);
        assert_eq!(CharType::from('{'), CharType::Other);
        assert_eq!(CharType::from(' '), CharType::Whitespace);
        assert_eq!(CharType::from('\t'), CharType::Whitespace);
        assert_eq!(CharType::from('\u{00A0}'), CharType::Whitespace);
        assert_eq!(CharType::from('\n'), CharType::Newline);
        assert_eq!(CharType::from('\r'), CharType::Newline);
        assert_eq!(CharType::from('汉'), CharType::Other);
        assert_eq!(CharType::from('é'), CharType::Word);
        assert_eq!(CharType::from('ä'), CharType::Word);
        assert_eq!(CharType::from('ö'), CharType::Word);
        assert_eq!(CharType::from('ü'), CharType::Word);
        assert_eq!(CharType::from('д'), CharType::Word);
    }

    #[test]
    fn test_word_range_at() {
        let text =
            "test text\nabcde 中文🎉 test\nhello[()]\ntest_connector ____\nRope\nrök\ngrande île";
        let tests = [
            (0, Some("test")),
            (4, Some(" ")),
            (10, Some("abcde")),
            (15, Some(" ")),
            (16, Some("中")),
            (19, Some("文")),
            (22, Some("🎉")),
            (27, Some("test")),
            (37, Some("[")),
            (38, Some("(")),
            (39, Some(")")),
            (40, Some("]")),
            (42, Some("test_connector")),
            (56, Some(" ")),
            (57, Some("____")),
            (62, Some("Rope")),
            (67, Some("rök")),
            (79, Some("île")),
        ];

        for (offset, expected) in tests {
            let actual = word_range_at(text, offset).map(|range| text[range].to_string());
            assert_eq!(actual.as_deref(), expected, "offset {offset}");
        }
    }
}
