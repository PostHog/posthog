use serde::{de::Error as _, Deserialize, Deserializer, Serialize};
use serde_json::Value;

use crate::core::types::frames::{Frame, RawFrame};

#[derive(Debug, Serialize, Clone)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Stacktrace {
    Raw { frames: Vec<RawFrame> },
    Resolved { frames: Vec<Frame> },
}

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
enum TaggedStacktrace {
    Raw { frames: Vec<RawFrame> },
    Resolved { frames: Vec<Frame> },
}

#[derive(Deserialize)]
struct UntaggedStacktrace {
    #[serde(default)]
    frames: Vec<RawFrame>,
}

/// Older SDKs sent the stacktrace without the `type` discriminant that tags this
/// enum (posthog-python before 5.x, for one). Only an SDK writes a stacktrace and
/// only ever a raw one, so an untagged payload is treated as raw rather than
/// failing the exception and costing it its frames.
impl<'de> Deserialize<'de> for Stacktrace {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        if value.get("type").is_some() {
            return match TaggedStacktrace::deserialize(value).map_err(D::Error::custom)? {
                TaggedStacktrace::Raw { frames } => Ok(Stacktrace::Raw { frames }),
                TaggedStacktrace::Resolved { frames } => Ok(Stacktrace::Resolved { frames }),
            };
        }

        let untagged = UntaggedStacktrace::deserialize(value).map_err(D::Error::custom)?;
        Ok(Stacktrace::Raw {
            frames: untagged.frames,
        })
    }
}
