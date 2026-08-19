//! lz-string ("lz64") decompression with a hard cap on the output.
//!
//! Old PostHog SDKs send payloads compressed with lz-string's
//! `compressToBase64`. The `lz-str` crate decompresses those in one shot with no
//! way to stop it: LZW rebuilds a back-reference dictionary as it goes, so a few
//! kilobytes of base64 can expand into gigabytes before the caller ever gets a
//! length to check. This is that decoder with the cap checked on every emit, so
//! an oversized payload is refused while it is still small.

use crate::CompressionError;

/// lz-string's base64 alphabet; a character's index is its 6-bit value.
const BASE64_KEY: &[u8; 65] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=";

const BITS_PER_CHAR: u8 = 6;
const START_CODE_BITS: u8 = 2;

/// Stream codes: a literal byte, a literal UTF-16 unit, end of stream.
const U8_CODE: u32 = 0;
const U16_CODE: u32 = 1;
const CLOSE_CODE: u32 = 2;

/// Code width grows with the dictionary, which the output cap bounds, so only
/// corrupt input gets here. Rejecting it keeps `1 << n` inside a `u32`.
const MAX_CODE_BITS: u8 = 31;

/// Decompress a string produced by lz-string's `compressToBase64`, refusing any
/// stream that would emit more than `max_output_units` UTF-16 code units.
///
/// Returns the raw UTF-16 units, as `lz_str::decompress_from_base64` does, so
/// callers convert to a `String` themselves.
///
/// The dictionary holds ranges into the output rather than its own copies, so
/// peak memory stays a small multiple of the cap instead of paying a heap
/// allocation per entry.
pub fn decompress_lz64_capped(
    compressed: &str,
    max_output_units: usize,
) -> Result<Vec<u16>, CompressionError> {
    // Ranges into the output are u32, so a larger cap could not be enforced.
    let limit = max_output_units.min(u32::MAX as usize);

    // Characters outside the alphabet are skipped, matching lz-string.
    let input = compressed.encode_utf16().filter_map(|c| {
        BASE64_KEY
            .iter()
            .position(|k| u32::from(c) == u32::from(*k))
            .map(|n| n as u16)
    });

    let mut reader = match BitReader::new(input, BITS_PER_CHAR) {
        Some(reader) => reader,
        None => return Ok(Vec::new()),
    };

    let first = match reader
        .read_bits(START_CODE_BITS)
        .ok_or(CompressionError::Lz64Invalid)?
    {
        code @ (U8_CODE | U16_CODE) => read_literal(&mut reader, code)?,
        CLOSE_CODE => return Ok(Vec::new()),
        _ => return Err(CompressionError::Lz64Invalid),
    };

    let mut out: Vec<u16> = Vec::new();
    // The three reserved codes above are intercepted before any lookup, so these
    // placeholder ranges are never read. They only keep dictionary indexes aligned.
    let mut dictionary: Vec<(u32, u32)> = vec![(0, 0); 3];

    push_unit(&mut out, first, limit)?;
    dictionary.push((0, 1));

    let mut w: (u32, u32) = (0, 1);
    let mut num_bits: u8 = 3;
    let mut enlarge_in: u64 = 4;

    loop {
        if num_bits > MAX_CODE_BITS {
            return Err(CompressionError::Lz64Invalid);
        }

        let mut code = reader
            .read_bits(num_bits)
            .ok_or(CompressionError::Lz64Invalid)?;
        let mut literal = None;

        match code {
            U8_CODE | U16_CODE => {
                literal = Some(read_literal(&mut reader, code)?);
                // The literal's entry is the single unit emitted below.
                dictionary.push((out_len(&out), 1));
                code = u32::try_from(dictionary.len() - 1)
                    .map_err(|_| CompressionError::Lz64Invalid)?;
                enlarge_in -= 1;
            }
            CLOSE_CODE => return Ok(out),
            _ => {}
        }

        if enlarge_in == 0 {
            enlarge_in = 1 << num_bits;
            num_bits += 1;
        }

        let entry = if let Some(unit) = literal {
            push_unit(&mut out, unit, limit)?;
            (out_len(&out) - 1, 1)
        } else if let Some(&(start, len)) = dictionary.get(code as usize) {
            copy_range(&mut out, start, len, limit)?;
            (out_len(&out) - len, len)
        } else if code as usize == dictionary.len() {
            // LZW's "code we are about to define" case: w plus w's first unit.
            let (start, len) = w;
            copy_range(&mut out, start, len, limit)?;
            let first_unit = out[start as usize];
            push_unit(&mut out, first_unit, limit)?;
            (out_len(&out) - len - 1, len + 1)
        } else {
            return Err(CompressionError::Lz64Invalid);
        };

        // w plus entry's first unit is contiguous in `out`: entry was emitted
        // directly after w, so its first unit sits one past the end of w.
        dictionary.push((w.0, w.1 + 1));
        enlarge_in -= 1;
        w = entry;

        if enlarge_in == 0 {
            enlarge_in = 1 << num_bits;
            num_bits += 1;
        }
    }
}

/// Reads the bit stream lz-string packs into base64 characters.
struct BitReader<I> {
    val: u16,
    data: I,
    position: u16,
    reset_val: u16,
}

impl<I: Iterator<Item = u16>> BitReader<I> {
    fn new(mut data: I, bits_per_char: u8) -> Option<Self> {
        let reset_val = 1 << (bits_per_char - 1);
        Some(BitReader {
            val: data.next()?,
            data,
            position: reset_val,
            reset_val,
        })
    }

    fn read_bit(&mut self) -> Option<bool> {
        let res = self.val & self.position;
        self.position >>= 1;

        if self.position == 0 {
            self.position = self.reset_val;
            self.val = self.data.next()?;
        }

        Some(res != 0)
    }

    fn read_bits(&mut self, n: u8) -> Option<u32> {
        let mut res = 0;
        let max_power: u32 = 1 << n;
        let mut power: u32 = 1;
        while power != max_power {
            res |= u32::from(self.read_bit()?) * power;
            power <<= 1;
        }

        Some(res)
    }
}

fn read_literal<I: Iterator<Item = u16>>(
    reader: &mut BitReader<I>,
    code: u32,
) -> Result<u16, CompressionError> {
    let bits_to_read = if code == U8_CODE { 8 } else { 16 };
    let value = reader
        .read_bits(bits_to_read)
        .ok_or(CompressionError::Lz64Invalid)?;

    u16::try_from(value).map_err(|_| CompressionError::Lz64Invalid)
}

/// The cap keeps the output within `u32::MAX` units, so this never truncates.
fn out_len(out: &[u16]) -> u32 {
    out.len() as u32
}

fn push_unit(out: &mut Vec<u16>, unit: u16, limit: usize) -> Result<(), CompressionError> {
    check_capacity(out.len(), 1, limit)?;
    out.push(unit);
    Ok(())
}

fn copy_range(
    out: &mut Vec<u16>,
    start: u32,
    len: u32,
    limit: usize,
) -> Result<(), CompressionError> {
    let (start, len) = (start as usize, len as usize);
    check_capacity(out.len(), len, limit)?;
    out.extend_from_within(start..start + len);
    Ok(())
}

fn check_capacity(current: usize, adding: usize, limit: usize) -> Result<(), CompressionError> {
    if current + adding > limit {
        return Err(CompressionError::Lz64OutputTooLarge {
            units: current + adding,
            limit,
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const GENEROUS_LIMIT: usize = 1024 * 1024;

    fn decompress_to_string(compressed: &str, limit: usize) -> Result<String, CompressionError> {
        let units = decompress_lz64_capped(compressed, limit)?;
        Ok(String::from_utf16(&units).unwrap())
    }

    /// This decoder is a port, so any divergence from `lz-str` silently drops
    /// data an SDK sent. Both roundtrip tests exist to catch that.
    #[test]
    fn matches_lz_str_on_roundtrips() {
        let cases = [
            "",
            "{}",
            r#"{"event":"$pageview","properties":{"$lib":"web"}}"#,
            // Repetition is what LZW's dictionary rewards, so exercise it.
            &r#"{"event":"$pageview"},"#.repeat(500),
            // Non-ASCII lands outside the u8 literal code path.
            r#"{"event":"クリック","emoji":"🦔","accents":"ãéî"}"#,
            &"a".repeat(100_000),
        ];

        for case in cases {
            let compressed = lz_str::compress_to_base64(case);
            let expected = lz_str::decompress_from_base64(&compressed).unwrap();

            assert_eq!(
                decompress_lz64_capped(&compressed, GENEROUS_LIMIT).unwrap(),
                expected,
                "diverged from lz-str on a {} char payload",
                case.len()
            );
            assert_eq!(
                decompress_to_string(&compressed, GENEROUS_LIMIT).unwrap(),
                case
            );
        }
    }

    #[test]
    fn matches_lz_str_on_generated_payloads() {
        // A seeded generator, so a divergence reproduces instead of flaking.
        let mut seed: u64 = 0x5eed;
        let mut next = move || {
            seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
            (seed >> 33) as usize
        };

        for case_index in 0..200 {
            // A small alphabet with structure keeps the dictionary busy, which is
            // where the port and lz-str could disagree.
            let alphabet = [
                "a",
                "b",
                "{",
                "}",
                "\"",
                ":",
                ",",
                "0",
                "$pageview",
                "properties",
                "🦔",
            ];
            let length = 1 + next() % 400;
            let payload: String = (0..length)
                .map(|_| alphabet[next() % alphabet.len()])
                .collect();

            let compressed = lz_str::compress_to_base64(&payload);

            assert_eq!(
                decompress_lz64_capped(&compressed, GENEROUS_LIMIT).unwrap(),
                lz_str::decompress_from_base64(&compressed).unwrap(),
                "diverged from lz-str on generated case {case_index}: {payload}"
            );
        }
    }

    #[test]
    fn rejects_a_decompression_bomb_without_materializing_it() {
        // ~2KB of base64 expanding to 1MB, well under any request body limit.
        let bomb = lz_str::compress_to_base64(&"a".repeat(1024 * 1024));
        assert!(bomb.len() < 16 * 1024);

        let result = decompress_lz64_capped(&bomb, 4096);

        assert!(matches!(
            result,
            Err(CompressionError::Lz64OutputTooLarge { limit, .. }) if limit == 4096
        ));
    }

    #[test]
    fn accepts_output_exactly_at_the_limit() {
        let payload = "b".repeat(4096);
        let compressed = lz_str::compress_to_base64(&payload);

        assert_eq!(decompress_to_string(&compressed, 4096).unwrap(), payload);
    }

    #[test]
    fn rejects_output_one_unit_over_the_limit() {
        let compressed = lz_str::compress_to_base64(&"b".repeat(4097));

        assert!(matches!(
            decompress_lz64_capped(&compressed, 4096),
            Err(CompressionError::Lz64OutputTooLarge { .. })
        ));
    }

    #[test]
    fn rejects_truncated_input() {
        let compressed = lz_str::compress_to_base64(r#"{"event":"$pageview"}"#);

        // Truncated mid-stream, and a stream that ends right after its first code.
        for case in [&compressed[..compressed.len() / 2], "A"] {
            assert!(
                matches!(
                    decompress_lz64_capped(case, GENEROUS_LIMIT),
                    Err(CompressionError::Lz64Invalid)
                ),
                "expected {case:?} to be rejected"
            );
        }
    }

    #[test]
    fn input_with_no_alphabet_characters_decodes_to_nothing() {
        // lz-string skips characters outside its alphabet, so these are empty streams.
        for case in ["", "!!!!"] {
            assert_eq!(
                decompress_lz64_capped(case, GENEROUS_LIMIT).unwrap(),
                lz_str::decompress_from_base64(case).unwrap()
            );
        }
    }
}
