//! The `AISR03` frame that seals every v3 and v4 object body.
//!
//! The frame is the ASCII magic, a big-endian `u16` length, the additional authenticated data, a 12-byte nonce, and
//! the AES-256-GCM ciphertext followed by its 16-byte tag. The authenticated data is the canonical JSON of
//! `{"v": <version>, "context": <context>}`, so the context binds the owner, the kind and the codec of the body.

use aes_gcm::aead::{Aead, AeadCore, KeyInit, OsRng, Payload};
use aes_gcm::{Aes256Gcm, Key, Nonce};
use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use serde_json::{Map, Value};

pub const MAGIC: &[u8; 6] = b"AISR03";
pub const NONCE_BYTES: usize = 12;
pub const TAG_BYTES: usize = 16;
const AAD_LENGTH_BYTES: usize = 2;
const HEADER_BYTES: usize = MAGIC.len() + AAD_LENGTH_BYTES;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum EnvelopeError {
    #[error("not an AISR03 frame")]
    NotAFrame,
    #[error("frame is shorter than its header says")]
    Truncated,
    #[error("frame context does not match the requested object")]
    ContextMismatch,
    #[error("authenticated data is too long to frame")]
    ContextTooLong,
    #[error("authentication failed")]
    Authentication,
}

/// The dataset version inside the authenticated data. A reader for one version never opens the other.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Version {
    V3 = 3,
    V4 = 4,
}

/// How the reader must expand the plaintext. It sits inside the authenticated context so it cannot be downgraded.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Codec {
    None,
    Brotli,
    Zstd,
}

impl Codec {
    pub fn as_str(self) -> &'static str {
        match self {
            Codec::None => "none",
            Codec::Brotli => "brotli",
            Codec::Zstd => "zstd",
        }
    }
}

/// The object a frame belongs to. Field names are the camelCase names the Node writers use.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Context {
    pub team_id: i64,
    pub session_id: Option<String>,
    pub key_month: Option<String>,
    pub session_month: Option<String>,
    pub organization_id: Option<String>,
    pub kind: String,
    pub codec: Option<Codec>,
    pub reference: Option<String>,
}

impl Context {
    fn to_json(&self) -> Value {
        let mut context = Map::new();
        context.insert("teamId".to_owned(), Value::from(self.team_id));
        let optional = [
            ("sessionId", &self.session_id),
            ("keyMonth", &self.key_month),
            ("sessionMonth", &self.session_month),
            ("organizationId", &self.organization_id),
        ];
        for (name, value) in optional {
            if let Some(value) = value {
                context.insert(name.to_owned(), Value::from(value.as_str()));
            }
        }
        context.insert("kind".to_owned(), Value::from(self.kind.as_str()));
        if let Some(codec) = self.codec {
            context.insert("codec".to_owned(), Value::from(codec.as_str()));
        }
        if let Some(reference) = &self.reference {
            context.insert("ref".to_owned(), Value::from(reference.as_str()));
        }
        Value::Object(context)
    }

    /// The bytes AES-GCM authenticates for this context.
    pub fn authenticated_data(&self, version: Version) -> String {
        let mut wrapper = Map::new();
        wrapper.insert("v".to_owned(), Value::from(version as u8));
        wrapper.insert("context".to_owned(), self.to_json());
        canonical_json(&Value::Object(wrapper))
    }
}

/// JSON with sorted keys and no whitespace, which the Node writers and every reader produce byte for byte.
pub fn canonical_json(value: &Value) -> String {
    let mut out = String::new();
    write_canonical(value, &mut out);
    out
}

fn write_canonical(value: &Value, out: &mut String) {
    match value {
        Value::Array(items) => {
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                write_canonical(item, out);
            }
            out.push(']');
        }
        Value::Object(entries) => {
            // Sort here rather than rely on the map type: a crate elsewhere in the build can turn on
            // serde_json's `preserve_order` feature, which changes the map to insertion order.
            let mut keys: Vec<&String> = entries.keys().collect();
            keys.sort();
            out.push('{');
            for (index, key) in keys.into_iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                out.push_str(&Value::from(key.as_str()).to_string());
                out.push(':');
                write_canonical(&entries[key], out);
            }
            out.push('}');
        }
        scalar => out.push_str(&scalar.to_string()),
    }
}

/// Seals `body` under `key` with a random nonce.
pub fn seal_frame(
    key: &[u8; 32],
    version: Version,
    context: &Context,
    body: &[u8],
) -> Result<Vec<u8>, EnvelopeError> {
    let nonce = Aes256Gcm::generate_nonce(&mut OsRng);
    seal_frame_with_nonce(key, version, context, body, nonce.into())
}

/// Seals with a caller-chosen nonce. Only the test vectors may fix a nonce: reusing one under a key breaks AES-GCM.
pub fn seal_frame_with_nonce(
    key: &[u8; 32],
    version: Version,
    context: &Context,
    body: &[u8],
    nonce: [u8; NONCE_BYTES],
) -> Result<Vec<u8>, EnvelopeError> {
    let aad = context.authenticated_data(version);
    let aad_length = u16::try_from(aad.len()).map_err(|_| EnvelopeError::ContextTooLong)?;
    let cipher = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(key));
    let sealed = cipher
        .encrypt(
            Nonce::from_slice(&nonce),
            Payload {
                msg: body,
                aad: aad.as_bytes(),
            },
        )
        .map_err(|_| EnvelopeError::Authentication)?;
    let mut frame = Vec::with_capacity(HEADER_BYTES + aad.len() + NONCE_BYTES + sealed.len());
    frame.extend_from_slice(MAGIC);
    frame.extend_from_slice(&aad_length.to_be_bytes());
    frame.extend_from_slice(aad.as_bytes());
    frame.extend_from_slice(&nonce);
    frame.extend_from_slice(&sealed);
    Ok(frame)
}

/// Opens a frame and checks it belongs to `context`.
///
/// The check is required: one key seals many objects, and the context is the only thing that tells them apart.
pub fn open_frame(
    key: &[u8; 32],
    version: Version,
    context: &Context,
    frame: &[u8],
) -> Result<Vec<u8>, EnvelopeError> {
    if frame.len() < HEADER_BYTES || &frame[..MAGIC.len()] != MAGIC {
        return Err(EnvelopeError::NotAFrame);
    }
    // The magic and the length sit outside the authenticated data, so bound the frame before slicing it.
    let aad_length = usize::from(u16::from_be_bytes([
        frame[MAGIC.len()],
        frame[MAGIC.len() + 1],
    ]));
    if frame.len() < HEADER_BYTES + aad_length + NONCE_BYTES + TAG_BYTES {
        return Err(EnvelopeError::Truncated);
    }
    let aad = &frame[HEADER_BYTES..HEADER_BYTES + aad_length];
    if aad != context.authenticated_data(version).as_bytes() {
        return Err(EnvelopeError::ContextMismatch);
    }
    let nonce = &frame[HEADER_BYTES + aad_length..HEADER_BYTES + aad_length + NONCE_BYTES];
    let sealed = &frame[HEADER_BYTES + aad_length + NONCE_BYTES..];
    let cipher = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(key));
    cipher
        .decrypt(Nonce::from_slice(nonce), Payload { msg: sealed, aad })
        .map_err(|_| EnvelopeError::Authentication)
}

/// Seals a Parquet column value as the base64 JSON envelope `{v, context, nonce, ciphertext}`.
///
/// The context carries no codec, as in v3: a column value is stored as it is.
pub fn seal_json_envelope(
    key: &[u8; 32],
    version: Version,
    context: &Context,
    data: &[u8],
) -> Result<Value, EnvelopeError> {
    let nonce = Aes256Gcm::generate_nonce(&mut OsRng);
    seal_json_envelope_with_nonce(key, version, context, data, nonce.into())
}

/// Seals with a caller-chosen nonce. Only the test vectors may fix a nonce.
pub fn seal_json_envelope_with_nonce(
    key: &[u8; 32],
    version: Version,
    context: &Context,
    data: &[u8],
    nonce: [u8; NONCE_BYTES],
) -> Result<Value, EnvelopeError> {
    let context = Context {
        codec: None,
        ..context.clone()
    };
    let aad = context.authenticated_data(version);
    let cipher = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(key));
    let sealed = cipher
        .encrypt(
            Nonce::from_slice(&nonce),
            Payload {
                msg: data,
                aad: aad.as_bytes(),
            },
        )
        .map_err(|_| EnvelopeError::Authentication)?;
    let mut envelope = Map::new();
    envelope.insert("v".to_owned(), Value::from(version as u8));
    envelope.insert("context".to_owned(), context.to_json());
    envelope.insert("nonce".to_owned(), Value::from(STANDARD.encode(nonce)));
    envelope.insert(
        "ciphertext".to_owned(),
        Value::from(STANDARD.encode(sealed)),
    );
    Ok(Value::Object(envelope))
}
