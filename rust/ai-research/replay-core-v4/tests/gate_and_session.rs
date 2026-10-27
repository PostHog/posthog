use replay_core_v4::gate::in_sample;
use replay_core_v4::session::{drop_reason, start_ms, DropReason};
use serde_json::Value;

// Verdicts from the session feature recorder's gate, run in Node on the ID as the replay lanes normalize it, so the two
// lanes keep selecting the same sessions in any casing.
const GATE: &str = include_str!("vectors/gate.json");

#[test]
fn gate_matches_the_feature_recorder() {
    let vector: Value = serde_json::from_str(GATE).unwrap();
    for case in vector["cases"].as_array().unwrap() {
        let session_id = case["sessionId"].as_str().unwrap();
        for (percentage, expected) in case["inSample"].as_object().unwrap() {
            assert_eq!(
                in_sample(session_id.as_bytes(), percentage.parse().unwrap()),
                expected.as_bool().unwrap(),
                "{session_id} at {percentage}%"
            );
        }
    }
}

#[test]
fn admits_only_recent_uuid_v7_sessions() {
    // 019a2f3e8c00 is 2025-10-28T16:30:22.592Z.
    let start = 0x019a_2f3e_8c00_i64;
    let day = 24 * 60 * 60 * 1000;
    let id = "019a2f3e-8c00-7000-8000-000000000007";
    assert_eq!(start_ms(id), Some(start));

    let cases = [
        (id, start, None),
        (id, start + 14 * day, None),
        (id, start + 14 * day + 1, Some(DropReason::TooOld)),
        (id, start - day, None),
        (id, start - day - 1, Some(DropReason::InFuture)),
        ("019A2F3E-8C00-7000-B000-000000000007", start, None),
        (
            "019a2f3e-8c00-4000-8000-000000000007",
            start,
            Some(DropReason::NotUuidV7),
        ),
        (
            "019a2f3e-8c00-7000-c000-000000000007",
            start,
            Some(DropReason::NotUuidV7),
        ),
        (
            "00000000-0000-7000-8000-000000000007",
            start,
            Some(DropReason::NotUuidV7),
        ),
        (
            "019a2f3e8c0070008000000000000007",
            start,
            Some(DropReason::NotUuidV7),
        ),
    ];
    for (session_id, now, expected) in cases {
        assert_eq!(
            drop_reason(session_id, now),
            expected,
            "{session_id} at {now}"
        );
    }
}
