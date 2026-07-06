//! Minimal protobuf wire-format scanner for extracting the person routing
//! key — `(team_id, person_id)` — from a leader request without a full
//! decode.
//!
//! The leader path forwards request bodies to leader pods verbatim; the
//! router only needs the routing key to pick the partition. A full proto
//! decode would force a re-encode on the way out and reject compressed
//! payloads. Instead we walk the wire format, read fields 1 and 2 as
//! varints, and skip every other field by its wire type.
//!
//! Correctness depends on a single invariant: across every leader request
//! type, `team_id` and `person_id` keep field numbers 1 and 2 with the
//! `int64` (varint) wire type. Backwards-compatible proto evolution
//! guarantees it — a field's number and wire type never change once
//! assigned — and the parity tests below pin it. Field *order* on the wire
//! is irrelevant: the scanner matches by field number and tolerates any
//! ordering, interleaving, or unknown fields.

/// Field numbers of the routing key, shared by every leader request type.
const TEAM_ID_FIELD: u64 = 1;
const PERSON_ID_FIELD: u64 = 2;

/// Protobuf varint wire type (`int64`, `uint32`, etc.).
const WIRE_VARINT: u8 = 0;
/// Protobuf 64-bit wire type (`fixed64`, `double`).
const WIRE_I64: u8 = 1;
/// Protobuf length-delimited wire type (`string`, `bytes`, sub-messages).
const WIRE_LEN: u8 = 2;
/// Protobuf 32-bit wire type (`fixed32`, `float`).
const WIRE_I32: u8 = 5;

#[derive(Debug, PartialEq, Eq)]
pub enum WireError {
    /// A varint ran past the end of the buffer or exceeded 10 bytes.
    MalformedVarint,
    /// A length-delimited or fixed-width field declared a length past the
    /// end of the buffer.
    TruncatedField,
    /// An unsupported wire type (the deprecated group markers, 3 and 4)
    /// was encountered.
    UnsupportedWireType(u8),
}

/// The person routing key extracted from a leader request body.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PersonKey {
    pub team_id: i64,
    pub person_id: i64,
}

/// Extract `(team_id, person_id)` from a serialized leader request message.
///
/// `msg` is the bare protobuf message (the gRPC length-prefix framing must
/// already be stripped). An absent key field decodes as `0`, matching
/// proto3 semantics: a scalar equal to its default is not encoded on the
/// wire, so "field absent" and "field is zero" are indistinguishable — and
/// `0` is exactly what a full decode would yield. The scan walks the whole
/// message rather than stopping once both keys are seen, for the same
/// parity reason: proto3 is last-one-wins for a scalar field that appears
/// more than once, and malformed bytes anywhere in the message would fail
/// the leader's own decode — so they fail here too, before we route.
/// Skipped fields cost one length read each; the payload bytes themselves
/// are never parsed.
pub fn scan_person_key(msg: &[u8]) -> Result<PersonKey, WireError> {
    let mut pos = 0;
    let mut team_id: i64 = 0;
    let mut person_id: i64 = 0;

    while pos < msg.len() {
        let tag = read_varint(msg, &mut pos)?;
        let field = tag >> 3;
        let wire_type = (tag & 0x7) as u8;

        match (field, wire_type) {
            (TEAM_ID_FIELD, WIRE_VARINT) => team_id = read_varint(msg, &mut pos)? as i64,
            (PERSON_ID_FIELD, WIRE_VARINT) => person_id = read_varint(msg, &mut pos)? as i64,
            _ => skip_field(msg, &mut pos, wire_type)?,
        }
    }

    Ok(PersonKey { team_id, person_id })
}

/// Read a base-128 varint starting at `*pos`, advancing `pos` past it.
/// Reads at most 10 bytes (the maximum encoding of a 64-bit value); a
/// longer run without a continuation-bit terminator is malformed.
fn read_varint(buf: &[u8], pos: &mut usize) -> Result<u64, WireError> {
    let mut result: u64 = 0;
    for i in 0..10u32 {
        let byte = *buf.get(*pos).ok_or(WireError::MalformedVarint)?;
        *pos += 1;
        result |= ((byte & 0x7f) as u64).wrapping_shl(i * 7);
        if byte & 0x80 == 0 {
            return Ok(result);
        }
    }
    Err(WireError::MalformedVarint)
}

/// Skip the value of a field whose tag was just read, given its wire type.
fn skip_field(buf: &[u8], pos: &mut usize, wire_type: u8) -> Result<(), WireError> {
    match wire_type {
        WIRE_VARINT => {
            read_varint(buf, pos)?;
        }
        WIRE_I64 => advance(buf, pos, 8)?,
        WIRE_LEN => {
            let len = read_varint(buf, pos)? as usize;
            advance(buf, pos, len)?;
        }
        WIRE_I32 => advance(buf, pos, 4)?,
        other => return Err(WireError::UnsupportedWireType(other)),
    }
    Ok(())
}

/// Advance `*pos` by `n` bytes, erroring if that would run past the buffer.
fn advance(buf: &[u8], pos: &mut usize, n: usize) -> Result<(), WireError> {
    let new = pos.checked_add(n).ok_or(WireError::TruncatedField)?;
    if new > buf.len() {
        return Err(WireError::TruncatedField);
    }
    *pos = new;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use personhog_proto::personhog::types::v1::{GetPersonRequest, UpdatePersonPropertiesRequest};
    use prost::Message;

    /// Append a varint to `buf` (test-local encoder for hand-built messages).
    fn put_varint(buf: &mut Vec<u8>, mut v: u64) {
        loop {
            let mut byte = (v & 0x7f) as u8;
            v >>= 7;
            if v != 0 {
                byte |= 0x80;
            }
            buf.push(byte);
            if v == 0 {
                break;
            }
        }
    }

    fn put_tag(buf: &mut Vec<u8>, field: u64, wire_type: u8) {
        put_varint(buf, (field << 3) | wire_type as u64);
    }

    /// The scanner must agree with a full prost decode of an
    /// `UpdatePersonPropertiesRequest` across a range of key values —
    /// this is the parity test that pins the field-number/wire-type
    /// invariant the scanner relies on.
    #[test]
    fn parity_with_update_person_properties_decode() {
        for (team_id, person_id) in [
            (1_i64, 42_i64),
            (0, 0),
            (i64::MAX, i64::MAX),
            (123_456, 9_876_543_210),
            (2, 1),
        ] {
            let req = UpdatePersonPropertiesRequest {
                team_id,
                person_id,
                event_name: "$set".to_string(),
                set_properties: vec![1, 2, 3, 4],
                set_once_properties: vec![5, 6],
                unset_properties: vec!["a".to_string(), "bb".to_string()],
            };
            let bytes = req.encode_to_vec();
            let key = scan_person_key(&bytes).expect("scan must succeed");
            assert_eq!(key.team_id, req.team_id);
            assert_eq!(key.person_id, req.person_id);
        }
    }

    /// Same parity check for `GetPersonRequest`, the other leader request
    /// type. Both must expose `team_id`/`person_id` at fields 1/2.
    #[test]
    fn parity_with_get_person_decode() {
        for (team_id, person_id) in [(1_i64, 42_i64), (i64::MAX, 1), (7, i64::MAX)] {
            let req = GetPersonRequest {
                team_id,
                person_id,
                read_options: None,
            };
            let bytes = req.encode_to_vec();
            let key = scan_person_key(&bytes).expect("scan must succeed");
            assert_eq!(key.team_id, req.team_id);
            assert_eq!(key.person_id, req.person_id);
        }
    }

    /// Field order on the wire is not guaranteed by protobuf, so the
    /// scanner must find the key regardless of position. Hand-build a
    /// message with field 2 before field 1, interleaved with a
    /// length-delimited field 3 and a varint field 7.
    #[test]
    fn finds_key_with_fields_out_of_order() {
        let mut buf = Vec::new();
        // field 3 (string), then person_id (field 2), then field 7
        // (varint), then team_id (field 1) — keys deliberately last and
        // reversed.
        put_tag(&mut buf, 3, WIRE_LEN);
        put_varint(&mut buf, 3);
        buf.extend_from_slice(b"abc");
        put_tag(&mut buf, 2, WIRE_VARINT);
        put_varint(&mut buf, 99);
        put_tag(&mut buf, 7, WIRE_VARINT);
        put_varint(&mut buf, 5);
        put_tag(&mut buf, 1, WIRE_VARINT);
        put_varint(&mut buf, 314);

        let key = scan_person_key(&buf).unwrap();
        assert_eq!(key.team_id, 314);
        assert_eq!(key.person_id, 99);
    }

    /// proto3 is last-one-wins when a scalar field appears more than once
    /// on the wire, so the scanner must be too — routing on the first
    /// occurrence while the leader decodes the last would send the request
    /// to the wrong partition. Prost is the parity oracle here.
    #[test]
    fn duplicated_key_field_is_last_one_wins() {
        let mut buf = Vec::new();
        put_tag(&mut buf, 1, WIRE_VARINT);
        put_varint(&mut buf, 7);
        put_tag(&mut buf, 2, WIRE_VARINT);
        put_varint(&mut buf, 42);
        // team_id appears again with a different value — last wins.
        put_tag(&mut buf, 1, WIRE_VARINT);
        put_varint(&mut buf, 9001);

        let decoded = GetPersonRequest::decode(&buf[..]).expect("prost accepts duplicates");
        assert_eq!(decoded.team_id, 9001);

        let key = scan_person_key(&buf).unwrap();
        assert_eq!(key.team_id, decoded.team_id);
        assert_eq!(key.person_id, decoded.person_id);
    }

    /// Malformed bytes after both keys must still fail the scan: the
    /// leader's own decode would reject the message, so routing it would
    /// only spend a wasted hop. Pins the full-scan (no early exit)
    /// behavior.
    #[test]
    fn malformed_bytes_after_keys_error() {
        let mut buf = Vec::new();
        put_tag(&mut buf, 1, WIRE_VARINT);
        put_varint(&mut buf, 1);
        put_tag(&mut buf, 2, WIRE_VARINT);
        put_varint(&mut buf, 2);
        // A length-delimited field declaring more bytes than remain.
        put_tag(&mut buf, 3, WIRE_LEN);
        put_varint(&mut buf, 100);
        buf.push(0xAA);

        assert!(GetPersonRequest::decode(&buf[..]).is_err(), "prost rejects");
        assert_eq!(scan_person_key(&buf), Err(WireError::TruncatedField));
    }

    /// Every non-key wire type preceding the keys must be skipped cleanly:
    /// fixed64 (wire 1), length-delimited (wire 2), and fixed32 (wire 5).
    #[test]
    fn skips_all_wire_types_before_keys() {
        let mut buf = Vec::new();
        put_tag(&mut buf, 10, WIRE_I64);
        buf.extend_from_slice(&[0u8; 8]);
        put_tag(&mut buf, 11, WIRE_LEN);
        put_varint(&mut buf, 4);
        buf.extend_from_slice(&[9u8; 4]);
        put_tag(&mut buf, 12, WIRE_I32);
        buf.extend_from_slice(&[0u8; 4]);
        put_tag(&mut buf, 1, WIRE_VARINT);
        put_varint(&mut buf, 8);
        put_tag(&mut buf, 2, WIRE_VARINT);
        put_varint(&mut buf, 16);

        let key = scan_person_key(&buf).unwrap();
        assert_eq!(key.team_id, 8);
        assert_eq!(key.person_id, 16);
    }

    /// An absent key field decodes as 0 (proto3 default), matching what a
    /// full prost decode yields. An empty message is `(0, 0)`; a message
    /// carrying only one key defaults the other to 0.
    #[test]
    fn absent_key_fields_default_to_zero() {
        assert_eq!(
            scan_person_key(&[]).unwrap(),
            PersonKey {
                team_id: 0,
                person_id: 0
            }
        );

        // Parity anchor: prost agrees that an empty message is (0, 0).
        let decoded = GetPersonRequest::decode(&[][..]).unwrap();
        assert_eq!(decoded.team_id, 0);
        assert_eq!(decoded.person_id, 0);

        let mut only_team = Vec::new();
        put_tag(&mut only_team, 1, WIRE_VARINT);
        put_varint(&mut only_team, 7);
        assert_eq!(
            scan_person_key(&only_team).unwrap(),
            PersonKey {
                team_id: 7,
                person_id: 0
            }
        );

        let mut only_person = Vec::new();
        put_tag(&mut only_person, 2, WIRE_VARINT);
        put_varint(&mut only_person, 9);
        assert_eq!(
            scan_person_key(&only_person).unwrap(),
            PersonKey {
                team_id: 0,
                person_id: 9
            }
        );
    }

    #[test]
    fn truncated_length_delimited_field_errors() {
        let mut buf = Vec::new();
        // Declares a 10-byte string but supplies none.
        put_tag(&mut buf, 3, WIRE_LEN);
        put_varint(&mut buf, 10);
        assert_eq!(scan_person_key(&buf), Err(WireError::TruncatedField));
    }

    #[test]
    fn malformed_varint_errors() {
        // A continuation bit set on every byte never terminates.
        let buf = vec![0x80u8; 11];
        assert_eq!(scan_person_key(&buf), Err(WireError::MalformedVarint));
    }

    #[test]
    fn group_wire_type_is_unsupported() {
        let mut buf = Vec::new();
        put_tag(&mut buf, 5, 3); // wire type 3 = group start (deprecated)
        assert_eq!(
            scan_person_key(&buf),
            Err(WireError::UnsupportedWireType(3))
        );
    }
}
