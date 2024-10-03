use std::ops::RangeInclusive;

use rand::RngCore;
use uuid::Uuid;

pub fn random_bytes<const N: usize>() -> [u8; N] {
    let mut ret = [0u8; N];
    rand::thread_rng().fill_bytes(&mut ret);
    ret
}

// basically just ripped from the uuid crate. they have it as unstable, but we can use it fine.
const fn encode_unix_timestamp_millis(millis: u64, random_bytes: &[u8; 10]) -> Uuid {
    let millis_high = ((millis >> 16) & 0xFFFF_FFFF) as u32;
    let millis_low = (millis & 0xFFFF) as u16;

    let random_and_version =
        (random_bytes[0] as u16 | ((random_bytes[1] as u16) << 8) & 0x0FFF) | (0x7 << 12);

    let mut d4 = [0; 8];

    d4[0] = (random_bytes[2] & 0x3F) | 0x80;
    d4[1] = random_bytes[3];
    d4[2] = random_bytes[4];
    d4[3] = random_bytes[5];
    d4[4] = random_bytes[6];
    d4[5] = random_bytes[7];
    d4[6] = random_bytes[8];
    d4[7] = random_bytes[9];

    Uuid::from_fields(millis_high, millis_low, random_and_version, &d4)
}

pub fn uuid_v7() -> Uuid {
    let bytes = random_bytes();
    let now = time::OffsetDateTime::now_utc();
    let now_millis: u64 = now.unix_timestamp() as u64 * 1_000 + now.millisecond() as u64;

    encode_unix_timestamp_millis(now_millis, &bytes)
}

// TODO - at some point, you really ought to just sit down and
// write a state machine
pub fn replace_invalid_hex_escape_strings(
    json_str: String,
) -> Result<String, std::string::FromUtf8Error> {
    // Consume the String and get its bytes
    let mut bytes = json_str.into_bytes();
    let len = bytes.len();
    let mut i = 0;

    const REPLACEMENT: &[u8; 4] = b"FFFD";
    const HIGH_SURROGATE_RANGE: RangeInclusive<u16> = 0xD800..=0xDBFF;
    const LOW_SURROGATE_RANGE: RangeInclusive<u16> = 0xDC00..=0xDFFF;

    let mut escaped = false;
    while i < len {
        // First, figure out if this byte is the start of an escape sequence,
        // and if it is, set the flag and move forward
        if bytes[i] == b'\\' {
            println!("found possible escape sequence at {}", i);
            escaped = !escaped; // Handle e.g. "\\u1234" as not an escape sequence
            println!("escaped: {}", escaped);
            i += 1;
            continue;
        }

        // If we're entering a hex escape
        if escaped && bytes[i] == b'u' {
            // Check if there are enough bytes for a Unicode escape sequence
            if i + 4 < len {
                // Extract the four escape sequence bytes
                let mut codepoint_bytes: [u8; 4] = [0; 4];
                codepoint_bytes.copy_from_slice(&bytes[i + 1..i + 5]);

                // Convert the bytes to a string, then parse it into a u16 to check if it's a valid escape sequence
                if let Ok(Ok(codepoint)) =
                    std::str::from_utf8(&codepoint_bytes).map(|s| u16::from_str_radix(s, 16))
                {
                    if (HIGH_SURROGATE_RANGE).contains(&codepoint) {
                        // High surrogate without a following low surrogate
                        if !is_next_low_surrogate(&bytes, i + 5) {
                            // Replace with 'FFFD' (Unicode replacement character)
                            codepoint_bytes.copy_from_slice(REPLACEMENT);
                        } else {
                            // This is a high surrogate, and the next is a low one, so we should skip over both
                            // without modification
                            i += 11; // u + 4 hex digits + \ + u + 4 hex digits = 11 bytes
                            escaped = false; // And exit the escape state
                            continue;
                        }
                    } else if (LOW_SURROGATE_RANGE).contains(&codepoint) {
                        // Unpaired low surrogate - we know this, because if it had a preceding high surrogate,
                        // we would have skipped over it in the previous iteration (above) - replace it
                        codepoint_bytes.copy_from_slice(REPLACEMENT);
                    }
                    // The unhandled else case is that this isn't part of a surrogate pair, so we don't need to do anything
                } else {
                    // if we couldn't parse those 4 bytes as a hex escape code, or couldn't go from that hex escape code to a u16, replace with 'FFFD'
                    codepoint_bytes.copy_from_slice(REPLACEMENT);
                }
                bytes[i + 1] = codepoint_bytes[0];
                bytes[i + 2] = codepoint_bytes[1];
                bytes[i + 3] = codepoint_bytes[2];
                bytes[i + 4] = codepoint_bytes[3];
                i += 5; // Move past the Unicode escape sequence
                escaped = false; // And exit the escape state
                continue;
            } else {
                // Not enough bytes for a Unicode escape sequence, truncate the buffer
                // to the 'u', and then append 'FFFD'
                bytes.truncate(i + 1);
                bytes.extend_from_slice(REPLACEMENT);
                break;
            }
        }

        i += 1;
    }

    // Convert bytes back to String
    String::from_utf8(bytes)
}

fn is_next_low_surrogate(bytes: &[u8], start: usize) -> bool {
    let len = bytes.len();
    // This doesn't need to look backwards - it's only used when we're already
    // parsing a high surrogate, and we're looking at the next 6 bytes
    if start + 6 <= len && bytes[start] == b'\\' && bytes[start + 1] == b'u' {
        let code_point_bytes = &bytes[start + 2..start + 6];
        if let Ok(code_point_str) = std::str::from_utf8(code_point_bytes) {
            if let Ok(num) = u16::from_str_radix(code_point_str, 16) {
                return (0xDC00..=0xDFFF).contains(&num);
            }
        }
    }
    false
}

#[cfg(test)]
mod test {

    #[test]
    pub fn treplace_unpaired_high_surrogate() {
        let json_str = r#"{"key":"\uD800"}"#.to_string();
        let expected = r#"{"key":"\uFFFD"}"#.to_string();
        assert_eq!(
            super::replace_invalid_hex_escape_strings(json_str).unwrap(),
            expected
        );
    }

    #[test]
    pub fn replace_unpaired_low_surrogate() {
        let json_str = r#"{"key":"\uDC00"}"#.to_string();
        let expected = r#"{"key":"\uFFFD"}"#.to_string();
        assert_eq!(
            super::replace_invalid_hex_escape_strings(json_str).unwrap(),
            expected
        );
    }

    #[test]
    pub fn replace_two_unpaired_low_surrogates() {
        let json_str = r#"{"key":"\uDC00\uDC00"}"#.to_string();
        let expected = r#"{"key":"\uFFFD\uFFFD"}"#.to_string();
        assert_eq!(
            super::replace_invalid_hex_escape_strings(json_str).unwrap(),
            expected
        );
    }

    #[test]
    pub fn replace_two_unpaired_high_surrogates() {
        let json_str = r#"{"key":"\uD800\uD800"}"#.to_string();
        let expected = r#"{"key":"\uFFFD\uFFFD"}"#.to_string();
        assert_eq!(
            super::replace_invalid_hex_escape_strings(json_str).unwrap(),
            expected
        );
    }

    #[test]
    pub fn replace_out_of_order_low_high_surrogates() {
        let json_str = r#"{"key":"\uDC00\uD800"}"#.to_string();
        let expected = r#"{"key":"\uFFFD\uFFFD"}"#.to_string();
        assert_eq!(
            super::replace_invalid_hex_escape_strings(json_str).unwrap(),
            expected
        );
    }

    #[test]
    pub fn replace_unfinished_surrogate() {
        let json_str = r#"{"key":"\uD800\uDC0"#.to_string();
        let expected = r#"{"key":"\uFFFD\uFFFD"#.to_string();
        assert_eq!(
            super::replace_invalid_hex_escape_strings(json_str).unwrap(),
            expected
        );
    }

    #[test]
    pub fn test_from_bad_data() {
        let string = include_str!("../tests/session_recording_utf_surrogate_console.json");
        let replaced = super::replace_invalid_hex_escape_strings(string.to_string()).unwrap();
        let _result: serde_json::Value = serde_json::from_str(&replaced).unwrap();
    }

    #[test]
    pub fn test_escaped_escape_sequences() {
        let json_str = r#"{"key":"\\uDC00"}"#.to_string();
        let expected = r#"{"key":"\\uDC00"}"#.to_string();
        assert_eq!(
            super::replace_invalid_hex_escape_strings(json_str).unwrap(),
            expected
        );
    }

    #[test]
    pub fn test_escaped_escaped_escaped_sequences() {
        let json_str = r#"{"key":"\\\uDC00"}"#.to_string();
        // Ordering is enter escape, find escaped \, enter escape, find invalid hex escape, replace with FFFD
        let expected = r#"{"key":"\\\uFFFD"}"#.to_string();
        assert_eq!(
            super::replace_invalid_hex_escape_strings(json_str).unwrap(),
            expected
        );
    }
}
