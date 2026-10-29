use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use replay_core_v4::envelope::{
    open_frame, seal_frame_with_nonce, seal_json_envelope_with_nonce, Codec, Context, Version,
};
use replay_core_v4::refs::{image_ref, image_url_ref, reference_hash, url_fingerprint};
use replay_core_v4::seal::{
    image_content_key, image_url_key, open_session_key, seal_session_key_with_nonce,
    url_fingerprint_key, SealedKey, WrappingContext,
};
use serde_json::Value;

// Written with Node's crypto from the spec in replay-data.md, so this checks the Rust code against an independent
// implementation. The v4 Node writers read the same file.
const VECTOR: &str =
    include_str!("../../../../nodejs/src/ingestion/pipelines/sessionreplay/ai-research/v4-keys/encryption-vector-v4.json");

fn vector() -> Value {
    serde_json::from_str(VECTOR).unwrap()
}

fn bytes(value: &Value) -> Vec<u8> {
    STANDARD.decode(value.as_str().unwrap()).unwrap()
}

fn key(value: &Value) -> [u8; 32] {
    bytes(value).try_into().unwrap()
}

fn nonce(value: &Value) -> [u8; 12] {
    bytes(value).try_into().unwrap()
}

fn str_field(value: &Value) -> Option<String> {
    value.as_str().map(str::to_owned)
}

fn context(value: &Value, codec: Option<Codec>) -> Context {
    Context {
        team_id: value["teamId"].as_i64().unwrap(),
        session_id: str_field(&value["sessionId"]),
        key_month: str_field(&value["keyMonth"]),
        kind: value["kind"].as_str().unwrap().to_owned(),
        codec,
        reference: str_field(&value["ref"]),
        ..Context::default()
    }
}

fn wrapping(vector: &Value) -> WrappingContext {
    WrappingContext {
        team_id: vector["identity"]["teamId"].as_i64().unwrap(),
        key_month: vector["identity"]["keyMonth"].as_str().unwrap().to_owned(),
        session_id: str_field(&vector["identity"]["sessionId"]),
    }
}

#[test]
fn reproduces_every_pinned_v4_value() {
    let vector = vector();
    let team_month_key = key(&vector["teamMonthKey"]);
    let session_key = key(&vector["sessionKey"]);
    let team_id = vector["identity"]["teamId"].as_i64().unwrap();
    let key_month = vector["identity"]["keyMonth"].as_str().unwrap();

    let sealed = seal_session_key_with_nonce(
        &team_month_key,
        &wrapping(&vector),
        &session_key,
        nonce(&vector["seal"]["nonce"]),
    );
    assert_eq!(sealed.sealed, bytes(&vector["seal"]["sealedKey"]));
    assert_eq!(
        open_session_key(&team_month_key, &wrapping(&vector), &sealed).unwrap(),
        session_key
    );

    assert_eq!(
        image_content_key(&team_month_key).to_vec(),
        bytes(&vector["derived"]["imageContentKey"])
    );
    assert_eq!(
        image_url_key(&team_month_key).to_vec(),
        bytes(&vector["derived"]["imageUrlKey"])
    );
    // Written with Python's hmac and hashlib from the same spec. The Node writers do not compute fingerprints.
    let fingerprint_key = url_fingerprint_key(&session_key);
    assert_eq!(
        STANDARD.encode(fingerprint_key),
        "wHU/NiuaLfC7MNU2/AT4BWzw9zZHycfzCV9bLEKAYgA="
    );
    assert_eq!(
        url_fingerprint(
            &fingerprint_key,
            "https://app.example.com/pricing?plan=team"
        ),
        "b08517cee3ff5ecc"
    );

    let block = &vector["block"];
    let block_context = context(&block["context"], Some(Codec::Brotli));
    assert_eq!(
        block_context.authenticated_data(Version::V4),
        block["aad"].as_str().unwrap()
    );
    let frame = seal_frame_with_nonce(
        &session_key,
        Version::V4,
        &block_context,
        &bytes(&block["body"]),
        nonce(&block["nonce"]),
    )
    .unwrap();
    assert_eq!(frame, bytes(&block["frame"]));
    assert_eq!(
        open_frame(&session_key, Version::V4, &block_context, &frame).unwrap(),
        bytes(&block["body"])
    );

    let image = &vector["image"];
    let hash = reference_hash(&image_content_key(&team_month_key), &bytes(&image["bytes"]));
    assert_eq!(
        image_ref(team_id, key_month, &hash),
        image["ref"].as_str().unwrap()
    );
    let image_context = context(&image["context"], Some(Codec::None));
    let image_frame = seal_frame_with_nonce(
        &team_month_key,
        Version::V4,
        &image_context,
        &bytes(&image["bytes"]),
        nonce(&image["nonce"]),
    )
    .unwrap();
    assert_eq!(image_frame, bytes(&image["frame"]));
    // Images are the team's, as the fetcher's are, so the team month key opens them and a session key does not.
    assert!(open_frame(&team_month_key, Version::V4, &image_context, &image_frame).is_ok());
    assert!(open_frame(&session_key, Version::V4, &image_context, &image_frame).is_err());

    let url = &vector["url"];
    let url_hash = reference_hash(
        &image_url_key(&team_month_key),
        url["url"].as_str().unwrap().as_bytes(),
    );
    assert_eq!(
        image_url_ref(team_id, key_month, &url_hash),
        url["ref"].as_str().unwrap()
    );

    // The image fetcher seals a fetched image under its URL reference, so a reader rebuilds the context from it.
    let fetched = &vector["imageUrl"];
    assert_eq!(fetched["ref"], url["ref"]);
    let fetched_context = context(&fetched["context"], Some(Codec::None));
    let fetched_frame = seal_frame_with_nonce(
        &team_month_key,
        Version::V4,
        &fetched_context,
        &bytes(&fetched["bytes"]),
        nonce(&fetched["nonce"]),
    )
    .unwrap();
    assert_eq!(fetched_frame, bytes(&fetched["frame"]));

    let index = &vector["index"];
    let envelope = seal_json_envelope_with_nonce(
        &session_key,
        Version::V4,
        &context(&index["context"], None),
        &bytes(&index["data"]),
        nonce(&index["envelope"]["nonce"]),
    )
    .unwrap();
    assert_eq!(envelope, index["envelope"]);
}

#[test]
fn a_sealed_session_key_opens_only_for_its_own_session_and_month() {
    let vector = vector();
    let team_month_key = key(&vector["teamMonthKey"]);
    let sealed = SealedKey {
        sealed: bytes(&vector["seal"]["sealedKey"]),
        nonce: nonce(&vector["seal"]["nonce"]),
    };
    let own = wrapping(&vector);

    let other_session = WrappingContext {
        session_id: Some("019a2f3e-8c00-7000-8000-000000000008".to_owned()),
        ..own.clone()
    };
    let other_month = WrappingContext {
        key_month: "2026-11".to_owned(),
        ..own.clone()
    };
    let other_team = WrappingContext { team_id: 8, ..own };
    for other in [other_session, other_month, other_team] {
        assert!(open_session_key(&team_month_key, &other, &sealed).is_err());
    }
}
