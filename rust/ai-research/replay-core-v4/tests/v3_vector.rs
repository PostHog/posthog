use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use replay_core_v4::envelope::{
    open_frame, seal_frame_with_nonce, Codec, Context, EnvelopeError, Version,
};
use serde_json::Value;

// The Node writer's pinned output. Both languages read this one file, so a drift on either side fails here.
const VECTOR: &str = include_str!("../../../../nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror/keys/encryption-vector.json");

fn vector() -> Value {
    serde_json::from_str(VECTOR).unwrap()
}

fn bytes(value: &Value) -> Vec<u8> {
    STANDARD.decode(value.as_str().unwrap()).unwrap()
}

fn frame_context(vector: &Value) -> Context {
    let context = &vector["context"];
    Context {
        team_id: context["teamId"].as_i64().unwrap(),
        session_id: Some(context["sessionId"].as_str().unwrap().to_owned()),
        organization_id: Some(context["organizationId"].as_str().unwrap().to_owned()),
        kind: vector["frame"]["kind"].as_str().unwrap().to_owned(),
        codec: Some(Codec::Brotli),
        ..Context::default()
    }
}

#[test]
fn seals_the_v3_frame_the_node_writer_pinned() {
    let vector = vector();
    let key: [u8; 32] = bytes(&vector["key"]).try_into().unwrap();
    let nonce: [u8; 12] = bytes(&vector["frame"]["nonce"]).try_into().unwrap();
    let context = frame_context(&vector);

    assert_eq!(
        context.authenticated_data(Version::V3),
        vector["frame"]["aad"].as_str().unwrap()
    );
    let frame = seal_frame_with_nonce(
        &key,
        Version::V3,
        &context,
        &bytes(&vector["frame"]["body"]),
        nonce,
    )
    .unwrap();
    assert_eq!(frame, bytes(&vector["frame"]["frame"]));
    assert_eq!(
        open_frame(&key, Version::V3, &context, &frame).unwrap(),
        bytes(&vector["frame"]["body"])
    );
}

#[test]
fn refuses_a_frame_for_another_object() {
    let vector = vector();
    let key: [u8; 32] = bytes(&vector["key"]).try_into().unwrap();
    let frame = bytes(&vector["frame"]["frame"]);
    let context = frame_context(&vector);

    let other_team = Context {
        team_id: 8,
        ..context.clone()
    };
    let other_codec = Context {
        codec: Some(Codec::None),
        ..context.clone()
    };
    for (other, version) in [
        (other_team, Version::V3),
        (other_codec, Version::V3),
        (context.clone(), Version::V4),
    ] {
        assert_eq!(
            open_frame(&key, version, &other, &frame),
            Err(EnvelopeError::ContextMismatch)
        );
    }
    let mut corrupted = frame.clone();
    let last = corrupted.len() - 1;
    corrupted[last] ^= 1;
    assert_eq!(
        open_frame(&key, Version::V3, &context, &corrupted),
        Err(EnvelopeError::Authentication)
    );
    assert_eq!(
        open_frame(&key, Version::V3, &context, &frame[..20]),
        Err(EnvelopeError::Truncated)
    );
}
