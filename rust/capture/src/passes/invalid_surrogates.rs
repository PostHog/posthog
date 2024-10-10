#[derive(Debug, PartialEq, Clone, Copy)]
enum LastSeen {
    Char,   // Any regular character
    Escape, // We've seen a backslash, not preceded by another backslash
}

// Unicode unknown character replacement - �, but as a hex escape sequence
const REPLACEMENT: &str = "uFFFD";
const HIGH_SURROGATE_RANGE: std::ops::Range<u16> = 0xD800..0xDBFF;
const LOW_SURROGATE_RANGE: std::ops::Range<u16> = 0xDC00..0xDFFF;

// This could be an iterator, that wraps a Chars<'_> and emits the correct characters. I'm
// /almost/ tempted to implement it, but I've already spent too long on this.

pub struct InvalidSurrogatesPass {
    // Clippy gives out because this this implies two layers of ptr indirection, but
    // in Self::run I'm partially moving Self, and this lets me do that without a clone
    #[allow(clippy::box_collection)]
    input: Box<String>,
    last_seen: LastSeen,
    output: Option<String>,
}

impl InvalidSurrogatesPass {
    pub fn new(input: String) -> Self {
        // Try to be a /little/ clever here, because this is in the path of
        // every request
        let output = if input.contains("\\u") {
            Some(String::with_capacity(input.len()))
        } else {
            None
        };
        Self {
            input: Box::new(input),
            last_seen: LastSeen::Char,
            output,
        }
    }

    fn emit(&mut self, c: char) {
        // Unwrap - this is only called by Self::run, which early-exits if output is None
        let output = self.output.as_mut().unwrap();
        if self.last_seen == LastSeen::Escape {
            // When we enter an escape sequence, we swallow the backslash,
            // to avoid having to backtrack if we drop an invalid escape sequence.
            // So we have to emit it here.
            output.push('\\');
            output.push(c);
            self.last_seen = LastSeen::Char;
        } else if c == '\\' {
            // If we're not already in an escape sequence, enter one, dropping the char to
            // avoid needing to backtrack
            self.last_seen = LastSeen::Escape;
        } else {
            // If we're not in an escape sequence, and not entering one, just push
            self.last_seen = LastSeen::Char;
            output.push(c);
        }
    }

    fn emit_str(&mut self, s: &str) {
        for c in s.chars() {
            self.emit(c);
        }
    }

    pub fn run(mut self) -> String {
        if self.output.is_none() {
            return *self.input;
        }

        // We need to mutably borrow self while emitting, and Chars<'_> immutably borrows from
        // the string it's iterating over, so we need to take the input out of self
        let input = std::mem::take(&mut *self.input);
        let mut chars = input.chars(); // We're iterating utf8 chars here, not bytes

        let mut buf = String::with_capacity(32);

        while let Some(c) = chars.next() {
            match (self.last_seen, c) {
                (LastSeen::Escape, 'u') => {
                    buf.clear();
                    if collect_n_chars(&mut buf, &mut chars, 4) < 4 {
                        // We didn't get enough characters to form a valid hex escape sequence
                        self.emit_str(REPLACEMENT);
                        continue;
                    }

                    // We have to assert these characters are hex digits, because we're going to parse them as such.
                    // Because these are utf8 chars, they could be emojis like 🤡, or anything else.
                    if buf.chars().any(|c| !c.is_ascii_hexdigit()) {
                        self.emit_str(REPLACEMENT);
                        continue;
                    }
                    // Unwrap safe because of the above
                    let first_code_point = u16::from_str_radix(&buf, 16).unwrap();

                    // Now, we try to get the second member of the surrogate pair, since we require surrogates to be paired
                    match chars.next() {
                        Some('\\') => {}
                        Some(c) => {
                            self.emit_str(REPLACEMENT);
                            self.emit(c);
                            continue;
                        }
                        None => {
                            // We didn't get a second escape sequence, so we just drop the first one
                            self.emit_str(REPLACEMENT);
                            continue;
                        }
                    }
                    match chars.next() {
                        Some('u') => {}
                        Some(c) => {
                            self.emit_str(REPLACEMENT);
                            self.emit(c);
                            continue;
                        }
                        None => {
                            self.emit_str(REPLACEMENT);
                            continue;
                        }
                    }

                    // Try to get the next hex sequence
                    buf.clear();
                    if collect_n_chars(&mut buf, &mut chars, 4) < 4 {
                        self.emit_str(REPLACEMENT);
                        self.emit_str(REPLACEMENT);
                        continue;
                    }
                    if buf.chars().any(|c| !c.is_ascii_hexdigit()) {
                        self.emit_str(REPLACEMENT);
                        self.emit_str(REPLACEMENT);
                        continue;
                    }
                    let second_code_point = u16::from_str_radix(&buf, 16).unwrap();

                    if HIGH_SURROGATE_RANGE.contains(&first_code_point)
                        && LOW_SURROGATE_RANGE.contains(&second_code_point)
                    {
                        // We have a valid pair of hex escapes, so we should push them.
                        // TODO - there's way to do this that doesn't require the
                        // allocation format! implies, but I'm not gonna work it out
                        // right now - we expect this to be /extremely/ rare
                        self.emit_str(&format!(
                            "\\u{:04X}\\u{:04X}",
                            first_code_point, second_code_point
                        ));
                    } else {
                        // We didn't get a valid pair, so we just drop the pair entirely
                        self.emit_str(REPLACEMENT);
                        self.emit_str(REPLACEMENT);
                    }
                }
                (LastSeen::Char | LastSeen::Escape, c) => {
                    // emit handles the transition between escape and char for us,
                    // so we just unconditionally emit here if the last thing we saw
                    // was a char, or the last thing we saw was an escape, AND the
                    // current char is not a 'u' (the case above)
                    self.emit(c);
                }
            }
        }

        // Unwrap - at the top of this function, we check for none, and return if it's found
        self.output.unwrap()
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
        let pass = super::InvalidSurrogatesPass::new(RAW_DATA.to_string());
        let data = pass.run();
        let res = serde_json::from_str::<RawEvent>(&data);
        assert!(res.is_ok())
    }
}
