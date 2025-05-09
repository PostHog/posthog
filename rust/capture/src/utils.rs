use axum::http::HeaderMap;
use base64::Engine;
use rand::RngCore;
use tracing::error;
use uuid::Uuid;

use crate::{
    api::CaptureError,
    v0_request::{Compression, EventFormData, EventQuery},
};

// used to limit test scans and extract loggable snippets from potentially large strings/buffers
pub const MAX_CHARS_TO_CHECK: usize = 128;
pub const MAX_PAYLOAD_SNIPPET_SIZE: usize = 20;

pub const FORM_MIME_TYPE: &str = "application/x-www-form-urlencoded";

#[derive(PartialEq, Eq)]
pub enum Base64Option {
    // hasn't been decoded from urlencoded payload; won't include spaces
    Strict,

    // input might have been urlencoded; might include spaces that need touching up
    Loose,

    // data may have originated in a URL query param (GET request) and may use alt characters
    URL,
}
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

pub fn extract_lib_version(form: &EventFormData, params: &EventQuery) -> Option<String> {
    let form_lv = form.lib_version.as_ref();
    let params_lv = params.lib_version.as_ref();
    if form_lv.is_some_and(|lv| !lv.is_empty()) {
        return Some(form_lv.unwrap().clone());
    }
    if params_lv.is_some_and(|lv| !lv.is_empty()) {
        return Some(params_lv.unwrap().clone());
    }

    None
}

// the compression hint can be tucked away any number of places depending on the SDK submitting the request...
pub fn extract_compression(
    form: &EventFormData,
    params: &EventQuery,
    headers: &HeaderMap,
) -> Compression {
    if params
        .compression
        .is_some_and(|c| c != Compression::Unsupported)
    {
        params.compression.unwrap()
    } else if form
        .compression
        .is_some_and(|c| c != Compression::Unsupported)
    {
        form.compression.unwrap()
    } else if let Some(ct) = headers.get("content-encoding") {
        match ct.to_str().unwrap_or("UNKNOWN") {
            "gzip" | "gzip-js" => Compression::Gzip,
            "lz64" | "lz-string" => Compression::LZString,
            _ => Compression::Unsupported,
        }
    } else {
        Compression::Unsupported
    }
}

pub fn decode_form(payload: &[u8]) -> Result<EventFormData, CaptureError> {
    match serde_urlencoded::from_bytes::<EventFormData>(payload) {
        Ok(form) => Ok(form),

        Err(e) => {
            let max_chars: usize = std::cmp::min(payload.len(), MAX_PAYLOAD_SNIPPET_SIZE);
            let form_data_snippet = String::from_utf8(payload[..max_chars].to_vec())
                .unwrap_or(String::from("INVALID_UTF8"));
            error!(
                form_data = form_data_snippet,
                "failed to decode urlencoded form body: {}", e
            );
            Err(CaptureError::RequestDecodingError(String::from(
                "invalid urlencoded form data",
            )))
        }
    }
}

// have we decoded sufficiently have a urlencoded data payload of the expected form yet?
pub fn is_likely_urlencoded_form(payload: &[u8]) -> bool {
    [
        &b"data="[..],
        &b"ver="[..],
        &b"_="[..],
        &b"ip="[..],
        &b"compression="[..],
    ]
    .iter()
    .any(|target: &&[u8]| payload.starts_with(target))
}

// relatively cheap check for base64 encoded payload since these can show up at
// various decoding layers in requests from different PostHog SDKs and versions
pub fn is_likely_base64(payload: &[u8], opt: Base64Option) -> bool {
    if payload.is_empty() {
        return false;
    }

    let prefix_chars_b64_compatible = payload.iter().take(MAX_CHARS_TO_CHECK).all(|b| {
        (*b >= b'A' && *b <= b'Z')
            || (*b >= b'a' && *b <= b'z')
            || (*b >= b'0' && *b <= b'9')
            || (opt != Base64Option::URL && (*b == b'+' || *b == b'/' || *b == b'='))
            || (opt == Base64Option::URL && (*b == b'_' || *b == b'-'))
            || (opt == Base64Option::Loose && *b == b' ')
    });

    let is_b64_aligned = payload.len() % 4 == 0;

    prefix_chars_b64_compatible && is_b64_aligned
}

pub fn decode_base64(payload: &[u8], location: &str) -> Result<Vec<u8>, CaptureError> {
    // TODO(eli): parameterize to use general_purpose::URL_SAFE_NO_PAD engine for GET req payloads
    match base64::engine::general_purpose::STANDARD.decode(payload) {
        Ok(decoded_payload) => Ok(decoded_payload),
        Err(e) => {
            let max_chars = std::cmp::min(payload.len(), MAX_PAYLOAD_SNIPPET_SIZE);
            let data_snippet = String::from_utf8(payload[..max_chars].to_vec())
                .unwrap_or(String::from("INVALID_UTF8"));
            error!(
                location = location,
                data_snippet = data_snippet,
                "decode_base64 failure: {}",
                e
            );
            Err(CaptureError::RequestDecodingError(String::from(
                "attempting to decode base64",
            )))
        }
    }
}
