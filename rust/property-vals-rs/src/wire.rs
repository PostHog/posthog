use std::fmt;

use crate::types::{PropertyType, PropertyValueMessage};

/// Compact binary format for intermediate topic records:
///
/// - magic + version header
/// - team_id (varint)
/// - type tag (0 = event, 1 = person, 2 = group + index byte)
/// - key (varint length + utf8 bytes)
/// - value (varint length + utf8 bytes)
/// - count (varint)
///
/// The magic byte distinguishes records from JSON (`{`) and the LZ4 frame
/// magic, so consumers can sniff which decoder to use.
pub const MAGIC: [u8; 3] = *b"PV\x01";

const TAG_EVENT: u8 = 0;
const TAG_PERSON: u8 = 1;
const TAG_GROUP: u8 = 2;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DecodeError(&'static str);

impl fmt::Display for DecodeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "wire decode error: {}", self.0)
    }
}

impl std::error::Error for DecodeError {}

pub fn encode(
    team_id: i64,
    property_type: PropertyType,
    property_key: &str,
    property_value: &str,
    property_count: u64,
) -> Vec<u8> {
    let mut buf =
        Vec::with_capacity(3 + 10 + 2 + 5 + property_key.len() + 5 + property_value.len() + 10);
    buf.extend_from_slice(&MAGIC);
    put_varint(&mut buf, team_id as u64);
    match property_type {
        PropertyType::Event => buf.push(TAG_EVENT),
        PropertyType::Person => buf.push(TAG_PERSON),
        PropertyType::Group(n) => {
            buf.push(TAG_GROUP);
            buf.push(n);
        }
    }
    put_str(&mut buf, property_key);
    put_str(&mut buf, property_value);
    put_varint(&mut buf, property_count);
    buf
}

pub fn decode(buf: &[u8]) -> Result<PropertyValueMessage, DecodeError> {
    if !buf.starts_with(&MAGIC) {
        return Err(DecodeError("missing magic header"));
    }
    let mut pos = MAGIC.len();
    let team_id = get_varint(buf, &mut pos)? as i64;
    let property_type = match get_byte(buf, &mut pos)? {
        TAG_EVENT => PropertyType::Event,
        TAG_PERSON => PropertyType::Person,
        TAG_GROUP => PropertyType::Group(get_byte(buf, &mut pos)?),
        _ => return Err(DecodeError("unknown property type tag")),
    };
    let property_key = get_str(buf, &mut pos)?;
    let property_value = get_str(buf, &mut pos)?;
    let property_count = get_varint(buf, &mut pos)?;
    if pos != buf.len() {
        return Err(DecodeError("trailing bytes"));
    }
    Ok(PropertyValueMessage {
        team_id,
        property_type,
        property_key,
        property_value,
        property_count,
    })
}

fn put_varint(buf: &mut Vec<u8>, mut v: u64) {
    loop {
        let byte = (v & 0x7f) as u8;
        v >>= 7;
        if v == 0 {
            buf.push(byte);
            return;
        }
        buf.push(byte | 0x80);
    }
}

fn get_varint(buf: &[u8], pos: &mut usize) -> Result<u64, DecodeError> {
    let mut out: u64 = 0;
    let mut shift = 0u32;
    loop {
        let byte = get_byte(buf, pos)?;
        let bits = u64::from(byte & 0x7f);
        // The round-trip check rejects payload bits that fall outside a u64,
        // e.g. bits 1-6 of a 10th byte (shift 63), which `<<` drops silently.
        if shift >= 64 || (bits << shift) >> shift != bits {
            return Err(DecodeError("varint overflow"));
        }
        out |= bits << shift;
        if byte & 0x80 == 0 {
            return Ok(out);
        }
        shift += 7;
    }
}

fn put_str(buf: &mut Vec<u8>, s: &str) {
    put_varint(buf, s.len() as u64);
    buf.extend_from_slice(s.as_bytes());
}

fn get_str(buf: &[u8], pos: &mut usize) -> Result<String, DecodeError> {
    let len = get_varint(buf, pos)? as usize;
    let end = pos.checked_add(len).ok_or(DecodeError("length overflow"))?;
    if end > buf.len() {
        return Err(DecodeError("string out of bounds"));
    }
    let s = std::str::from_utf8(&buf[*pos..end]).map_err(|_| DecodeError("invalid utf8"))?;
    *pos = end;
    Ok(s.to_string())
}

fn get_byte(buf: &[u8], pos: &mut usize) -> Result<u8, DecodeError> {
    let b = *buf
        .get(*pos)
        .ok_or(DecodeError("unexpected end of buffer"))?;
    *pos += 1;
    Ok(b)
}

#[cfg(test)]
mod tests {
    use proptest::prelude::*;

    use super::*;
    use crate::producer::Outgoing;
    use crate::types::IngestableEvent;

    fn round_trip(team_id: i64, pt: PropertyType, key: &str, value: &str, count: u64) {
        let buf = encode(team_id, pt, key, value, count);
        let decoded = decode(&buf).unwrap();
        assert_eq!(decoded.team_id, team_id);
        assert_eq!(decoded.property_type, pt);
        assert_eq!(decoded.property_key, key);
        assert_eq!(decoded.property_value, value);
        assert_eq!(decoded.property_count, count);
    }

    #[test]
    fn round_trips_all_property_types() {
        round_trip(
            2,
            PropertyType::Event,
            "$current_url",
            "https://posthog.com/",
            3,
        );
        round_trip(1, PropertyType::Person, "email", "a@b.co", 1);
        round_trip(i64::MAX, PropertyType::Group(0), "plan", "scale", u64::MAX);
        round_trip(42, PropertyType::Group(255), "", "", 0);
        round_trip(7, PropertyType::Event, "ключ", "значение🦔", 12345678901234);
    }

    #[test]
    fn rejects_garbage_and_truncation() {
        assert!(decode(b"not a wire record").is_err());
        assert!(decode(&[]).is_err());
        let buf = encode(2, PropertyType::Event, "k", "v", 1);
        for cut in 0..buf.len() {
            assert!(
                decode(&buf[..cut]).is_err(),
                "truncation at {cut} must error"
            );
        }
        let mut trailing = buf.clone();
        trailing.push(0);
        assert!(decode(&trailing).is_err());
    }

    #[test]
    fn rejects_varint_overflow() {
        // count is the last field, so the buffer's final byte is the 10th
        // byte of the u64::MAX varint (0x01, the only valid value there).
        let buf = encode(2, PropertyType::Event, "k", "v", u64::MAX);
        let last = buf.len() - 1;
        assert_eq!(buf[last], 0x01);

        for tenth_byte in [0x02, 0x7f] {
            let mut corrupted = buf.clone();
            corrupted[last] = tenth_byte;
            assert!(
                decode(&corrupted).is_err(),
                "10th byte {tenth_byte:#04x} carries bits past u64 and must error"
            );
        }

        let mut eleven_bytes = buf.clone();
        eleven_bytes[last] = 0x81;
        eleven_bytes.push(0x00);
        assert!(decode(&eleven_bytes).is_err(), "11-byte varint must error");
    }

    #[test]
    fn binary_is_smaller_than_json() {
        let key = "$current_url";
        let value = "https://us.posthog.com/project/2/insights/abc123";
        let binary = encode(2, PropertyType::Event, key, value, 7).len();
        let json = serde_json::json!({
            "team_id": 2,
            "property_type": "event",
            "property_key": key,
            "property_value": value,
            "property_count": 7,
        })
        .to_string()
        .len();
        assert!(
            binary < json / 2,
            "binary {binary} should be under half of json {json}"
        );
    }

    fn arb_property_type() -> impl Strategy<Value = PropertyType> {
        prop_oneof![
            Just(PropertyType::Event),
            Just(PropertyType::Person),
            any::<u8>().prop_map(PropertyType::Group),
        ]
    }

    proptest! {
        #[test]
        fn round_trips_any_message(
            team_id: i64,
            property_type in arb_property_type(),
            key in ".*",
            value in ".*",
            count: u64,
        ) {
            let decoded = decode(&encode(team_id, property_type, &key, &value, count)).unwrap();
            prop_assert_eq!(decoded.team_id, team_id);
            prop_assert_eq!(decoded.property_type, property_type);
            prop_assert_eq!(decoded.property_key, key);
            prop_assert_eq!(decoded.property_value, value);
            prop_assert_eq!(decoded.property_count, count);
        }

        // Flipping the producer's wire format must not change what the
        // merger sees: both encodings of a message decode identically.
        #[test]
        fn binary_and_json_decode_agree(
            team_id: i64,
            property_type in arb_property_type(),
            key in ".*",
            value in ".*",
            count: u64,
        ) {
            let json = serde_json::to_vec(&Outgoing {
                team_id,
                property_type,
                property_key: &key,
                property_value: &value,
                property_count: count,
            })
            .unwrap();
            let binary = encode(team_id, property_type, &key, &value, count);

            let from_json = PropertyValueMessage::decode(&json).unwrap();
            let from_binary = PropertyValueMessage::decode(&binary).unwrap();
            prop_assert_eq!(&from_json.team_id, &from_binary.team_id);
            prop_assert_eq!(&from_json.property_type, &from_binary.property_type);
            prop_assert_eq!(&from_json.property_key, &from_binary.property_key);
            prop_assert_eq!(&from_json.property_value, &from_binary.property_value);
            prop_assert_eq!(&from_json.property_count, &from_binary.property_count);
        }

        // Random bytes after a valid magic drive the parser deep into the
        // varint/string paths; it must reject or accept, never panic.
        #[test]
        fn decode_never_panics(garbage in proptest::collection::vec(any::<u8>(), 0..256)) {
            drop(decode(&garbage));
            let mut with_magic = MAGIC.to_vec();
            with_magic.extend_from_slice(&garbage);
            drop(decode(&with_magic));
        }

        #[test]
        fn corrupted_encodings_never_panic_and_truncations_error(
            team_id: i64,
            property_type in arb_property_type(),
            key in ".*",
            value in ".*",
            count: u64,
            flipped_byte in any::<prop::sample::Index>(),
            flipped_bit in 0u8..8,
        ) {
            let buf = encode(team_id, property_type, &key, &value, count);

            let mut corrupted = buf.clone();
            let i = flipped_byte.index(corrupted.len());
            corrupted[i] ^= 1 << flipped_bit;
            drop(decode(&corrupted));

            let cut = flipped_byte.index(buf.len());
            prop_assert!(decode(&buf[..cut]).is_err(), "truncation at {} must error", cut);
        }
    }
}
