use std::str::Chars;

#[derive(Debug, PartialEq, Clone, Copy)]
enum LastSeen {
    Char,   // Any regular character
    Escape, // We've seen a backslash, not preceded by another backslash
}

// Unicode unknown character replacement - �, but as a hex escape sequence
const REPLACEMENT: &str = "uFFFD";
const HIGH_SURROGATE_RANGE: std::ops::Range<u16> = 0xD800..0xDBFF;
const LOW_SURROGATE_RANGE: std::ops::Range<u16> = 0xDC00..0xDFFF;
const HEX_ESCAPE_LENGTH: usize = 4;

pub struct InvalidSurrogatesPass<'a> {
    input: Chars<'a>,
    last_seen: LastSeen,
    pending_output: Vec<char>,
    pending_ptr: usize,
    escape_seq_buf: String,
}

impl<'a> Iterator for InvalidSurrogatesPass<'a> {
    type Item = char;

    fn next(&mut self) -> Option<Self::Item> {
        self.step()
    }
}

impl<'a> InvalidSurrogatesPass<'a> {
    pub fn new(input: Chars<'a>) -> Self {
        Self {
            input,
            last_seen: LastSeen::Char,
            pending_output: Vec::with_capacity(32),
            pending_ptr: 0,
            escape_seq_buf: String::with_capacity(32),
        }
    }

    fn queue(&mut self, c: char) {
        if self.last_seen == LastSeen::Escape {
            // When we enter an escape sequence, we swallow the backslash,
            // to avoid having to backtrack if we drop an invalid escape sequence.
            // So we have to emit it here.
            self.pending_output.push('\\');
            self.pending_output.push(c);
            self.last_seen = LastSeen::Char;
        } else if c == '\\' {
            // If we're not already in an escape sequence, enter one, dropping the char to
            // avoid needing to backtrack
            self.last_seen = LastSeen::Escape;
        } else {
            // If we're not in an escape sequence, and not entering one, just push
            self.last_seen = LastSeen::Char;
            self.pending_output.push(c);
        }
    }

    fn queue_str(&mut self, s: &str) {
        for c in s.chars() {
            self.queue(c);
        }
    }

    fn pop(&mut self) -> Option<char> {
        // We push chars into the buffer reading left-to-right, and need to emit them
        // in the same order, so we have to track our stack index, and reset it when we
        // run out of chars to pop.
        if self.pending_ptr < self.pending_output.len() {
            let c = self.pending_output[self.pending_ptr];
            self.pending_ptr += 1;
            Some(c)
        } else {
            self.pending_output.clear();
            self.pending_ptr = 0;
            None
        }
    }

    fn step(&mut self) -> Option<char> {
        if let Some(c) = self.pop() {
            return Some(c);
        }

        // We're out of input, and we've go no pending output, so we're done
        let Some(c) = self.input.next() else {
            // If we're all out of input and the last thing we saw was an escape,
            // we have to emit that escape character. We just do that directly here,
            // knowing the next call around we'll return None.
            // Note that since we're parsing strings to get turned into json values,
            // we technically know this will be immediately discarded, but there's
            // no harm making it "correct" first.
            if self.last_seen == LastSeen::Escape {
                self.last_seen = LastSeen::Char;
                return Some('\\');
            };
            return None;
        };

        match (self.last_seen, c) {
            (LastSeen::Escape, 'u') => {
                let first_code_point =
                    match collect_escape_sequence(&mut self.escape_seq_buf, &mut self.input) {
                        Ok(code_point) => code_point,
                        Err(None) => {
                            // We ran out of chars. Push a replacement, and return.
                            // We drop the collected chars here because, if we'd encountered a syntactically
                            // important one, it would have been caught as non-hex earlier and returned in
                            // the branch below.
                            self.queue_str(REPLACEMENT);
                            return self.pop();
                        }
                        Err(Some(c)) => {
                            // We encountered an invalid char. Push the replacement, push the invalid char, and return
                            self.queue_str(REPLACEMENT);
                            self.queue(c);
                            return self.pop();
                        }
                    };

                // Now, we try to get the second member of the surrogate pair, since we require surrogates to be paired
                match self.input.next() {
                    Some('\\') => {
                        // We don't push a backslash here because we're already in an escape sequence,
                        // and it would cause us to exit it - but the specific characters we're going
                        // to emit isn't known yet, so we can't push those and then a backslash either
                    }
                    Some(c) => {
                        self.queue_str(REPLACEMENT);
                        self.queue(c);
                        return self.pop();
                    }
                    None => {
                        // We didn't get a second escape sequence, so we just drop the first one
                        self.queue_str(REPLACEMENT);
                        return self.pop();
                    }
                }
                match self.input.next() {
                    Some('u') => {}
                    Some(c) => {
                        self.queue_str(REPLACEMENT);
                        self.queue('\\'); // We have to handle that we've already consumed a backslash
                        self.queue(c);
                        return self.pop();
                    }
                    None => {
                        self.queue_str(REPLACEMENT);
                        self.queue('\\'); // As above
                        return self.pop();
                    }
                }

                let second_code_point =
                    match collect_escape_sequence(&mut self.escape_seq_buf, &mut self.input) {
                        Ok(code_point) => code_point,
                        Err(None) => {
                            self.queue_str(REPLACEMENT);
                            self.queue('\\');
                            self.queue_str(REPLACEMENT);
                            return self.pop();
                        }
                        Err(Some(c)) => {
                            self.queue_str(REPLACEMENT);
                            self.queue('\\');
                            self.queue_str(REPLACEMENT);
                            self.queue(c);
                            return self.pop();
                        }
                    };
                if HIGH_SURROGATE_RANGE.contains(&first_code_point)
                    && LOW_SURROGATE_RANGE.contains(&second_code_point)
                {
                    // We have a valid pair of hex escapes, so we should push them.
                    // TODO - there's way to do this that doesn't require the
                    // allocation format! implies, but I'm not gonna work it out
                    // right now - we expect this to be /extremely/ rare
                    self.queue_str(&format!(
                        "u{:04X}\\u{:04X}", // First backslash is already in the buffer due to last_seen
                        first_code_point, second_code_point
                    ));
                } else {
                    // We didn't get a valid pair, so we just drop the pair entirely
                    self.queue_str(REPLACEMENT);
                    self.queue('\\');
                    self.queue_str(REPLACEMENT);
                }
            }
            (LastSeen::Char | LastSeen::Escape, c) => {
                // emit handles the transition between escape and char for us,
                // so we just unconditionally emit here if the last thing we saw
                // was a char, or the last thing we saw was an escape, AND the
                // current char is not a 'u' (the case above)
                self.queue(c);
            }
        }

        // Because we swallow escape chars to avoid backtracking, we have to recurse
        // here to handle the case where we just entered an escape squeuence
        self.next()
    }
}

// Collects 4 chars into a hex escape sequence, returning the first char that couldn't be part of
// one, if one was found. If we run out of input, we return Result::Err(None)
fn collect_escape_sequence(
    buf: &mut String,
    iter: &mut dyn Iterator<Item = char>,
) -> Result<u16, Option<char>> {
    buf.clear();
    for _ in 0..HEX_ESCAPE_LENGTH {
        let Some(c) = iter.next() else {
            return Err(None);
        };
        // If this character couldn't be part of a hex escape sequence, we return it
        if !c.is_ascii_hexdigit() {
            return Err(Some(c));
        }
        buf.push(c);
    }
    // Unwrap safe due to the checking above
    Ok(u16::from_str_radix(buf, 16).unwrap())
}

#[cfg(test)]
mod test {

    use crate::v0_request::RawEvent;

    use super::InvalidSurrogatesPass;

    const RAW_DATA: &str = include_str!("../../tests/invalid_surrogate.json");

    #[test]
    fn test() {
        let pass = super::InvalidSurrogatesPass::new(RAW_DATA.chars());
        let data = pass.collect::<String>();
        let res = serde_json::from_str::<RawEvent>(&data);
        assert!(res.is_ok())
    }

    #[test]
    fn test_unpaired_high_surrogate() {
        let raw_data = r#"{"event":"\uD800"}"#;
        let pass = super::InvalidSurrogatesPass::new(raw_data.chars());
        let data = pass.collect::<String>();
        assert_eq!(data, r#"{"event":"\uFFFD"}"#);
    }

    #[test]
    fn test_unpaired_low_surrogate() {
        let raw_data = r#"{"event":"\uDC00"}"#;
        let pass = super::InvalidSurrogatesPass::new(raw_data.chars());
        let data = pass.collect::<String>();
        assert_eq!(data, r#"{"event":"\uFFFD"}"#);
    }

    #[test]
    fn test_wrong_order_surrogate_pair() {
        let raw_data = r#"{"event":"\uDC00\uD800"}"#;
        let pass = super::InvalidSurrogatesPass::new(raw_data.chars());
        let data = pass.collect::<String>();
        assert_eq!(data, r#"{"event":"\uFFFD\uFFFD"}"#);
    }

    #[test]
    fn test_trailing_escape() {
        let raw_data = r#"{"event":"\u"}"#;
        let pass = super::InvalidSurrogatesPass::new(raw_data.chars());
        let data = pass.collect::<String>();
        assert_eq!(data, r#"{"event":"\uFFFD"}"#);
    }

    #[test]
    fn test_trailing_escape_pair() {
        let raw_data = r#"{"event":"\u\u"}"#;
        let pass = super::InvalidSurrogatesPass::new(raw_data.chars());
        let data = pass.collect::<String>();
        assert_eq!(data, r#"{"event":"\uFFFD\uFFFD"}"#);
    }

    #[test]
    fn test_trailing_escape_pair_high_surrogate() {
        let raw_data = r#"{"event":"\uD800\u"}"#;
        let pass = super::InvalidSurrogatesPass::new(raw_data.chars());
        let data = pass.collect::<String>();
        assert_eq!(data, r#"{"event":"\uFFFD\uFFFD"}"#);
    }

    #[test]
    fn test_trailing_escape_pair_low_surrogate() {
        let raw_data = r#"{"event":"\uDC00\u"}"#;
        let pass = super::InvalidSurrogatesPass::new(raw_data.chars());
        let data = pass.collect::<String>();
        assert_eq!(data, r#"{"event":"\uFFFD\uFFFD"}"#);
    }

    #[test]
    fn test_trailing_escape_char() {
        let raw_data = r#"{"event":"\uD800\"#;
        let pass = super::InvalidSurrogatesPass::new(raw_data.chars());
        let data = pass.collect::<String>();
        assert_eq!(data, r#"{"event":"\uFFFD\"#);
    }

    #[test]
    fn test_valid_pair_trailing_slash() {
        let raw_data = r#"{"event":"\uD800\uDC00\"#;
        let pass = super::InvalidSurrogatesPass::new(raw_data.chars());
        let data = pass.collect::<String>();
        assert_eq!(data, r#"{"event":"\uD800\uDC00\"#);
    }

    #[test]
    fn it_handles_normal_data() {
        let raw_data = r#"{"event":"\uD800\uDC00"}"#;
        let pass = super::InvalidSurrogatesPass::new(raw_data.chars());
        let data = pass.collect::<String>();
        assert_eq!(data, r#"{"event":"\uD800\uDC00"}"#);
    }

    #[test]
    fn it_handles_data_with_no_surrogates() {
        let raw_data = r#"{"event":"\n"}"#;
        let pass = super::InvalidSurrogatesPass::new(raw_data.chars());
        let data = pass.collect::<String>();
        assert_eq!(data, r#"{"event":"\n"}"#);
    }

    #[test]
    fn it_handles_actual_session_data() {
        let data = include_str!("../../tests/session-example-event.json");
        let data = InvalidSurrogatesPass::new(data.chars()).collect::<String>();
        let event: RawEvent = serde_json::from_str(&data).unwrap();
        let out = serde_json::to_string(&event).unwrap();
        // Assert that the output does not contain and replacement characters
        assert!(!out.contains('�'));
    }
}
