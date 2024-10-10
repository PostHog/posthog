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
    // This is a simple heuristic to determine if we need to run this pass
    pub fn needed(input: &str) -> bool {
        input.contains("\\u")
    }

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
                self.escape_seq_buf.clear();
                if collect_n_chars(&mut self.escape_seq_buf, &mut self.input, 4) < 4 {
                    // We didn't get enough characters to form a valid hex escape sequence
                    self.queue_str(REPLACEMENT);
                    return self.pop();
                }

                // We have to assert these characters are hex digits, because we're going to parse them as such.
                // Because these are utf8 chars, they could be emojis like 🤡, or anything else.
                if self.escape_seq_buf.chars().any(|c| !c.is_ascii_hexdigit()) {
                    self.queue_str(REPLACEMENT);
                    return self.pop();
                }
                // Unwrap safe because of the above
                let first_code_point = u16::from_str_radix(&self.escape_seq_buf, 16).unwrap();

                // Now, we try to get the second member of the surrogate pair, since we require surrogates to be paired
                match self.input.next() {
                    Some('\\') => {}
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
                        self.queue(c);
                        return self.pop();
                    }
                    None => {
                        self.queue_str(REPLACEMENT);
                        return self.pop();
                    }
                }

                // Try to get the next hex sequence
                self.escape_seq_buf.clear();
                if collect_n_chars(&mut self.escape_seq_buf, &mut self.input, 4) < 4 {
                    self.queue_str(REPLACEMENT);
                    self.queue_str(REPLACEMENT);
                    return self.pop();
                }
                if self.escape_seq_buf.chars().any(|c| !c.is_ascii_hexdigit()) {
                    self.queue_str(REPLACEMENT);
                    self.queue_str(REPLACEMENT);
                    return self.pop();
                }
                let second_code_point = u16::from_str_radix(&self.escape_seq_buf, 16).unwrap();

                if HIGH_SURROGATE_RANGE.contains(&first_code_point)
                    && LOW_SURROGATE_RANGE.contains(&second_code_point)
                {
                    // We have a valid pair of hex escapes, so we should push them.
                    // TODO - there's way to do this that doesn't require the
                    // allocation format! implies, but I'm not gonna work it out
                    // right now - we expect this to be /extremely/ rare
                    self.queue_str(&format!(
                        "\\u{:04X}\\u{:04X}",
                        first_code_point, second_code_point
                    ));
                } else {
                    // We didn't get a valid pair, so we just drop the pair entirely
                    self.queue_str(REPLACEMENT);
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

// Collects up to limit chars into a string, returning the number of chars collected
fn collect_n_chars(
    string: &mut String,
    iter: &mut dyn Iterator<Item = char>,
    limit: usize,
) -> usize {
    for i in 0..limit {
        if let Some(c) = iter.next() {
            string.push(c);
        } else {
            return i;
        }
    }
    limit
}

#[cfg(test)]
mod test {
    use crate::v0_request::RawEvent;

    const RAW_DATA: &str = include_str!("../../tests/invalid_surrogate.json");

    #[test]
    fn test() {
        let pass = super::InvalidSurrogatesPass::new(RAW_DATA.chars());
        let data = pass.collect::<String>();
        let res = serde_json::from_str::<RawEvent>(&data);
        assert!(res.is_ok())
    }
}
