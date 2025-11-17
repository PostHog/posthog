use serde::{self, Deserialize, Serialize};

#[derive(Debug, Clone, Hash, Eq, PartialEq)]
pub struct RawFrameId {
    pub hash_id: String,
    pub team_id: i32,
}

impl RawFrameId {
    pub fn new(hash_id: String, team_id: i32) -> Self {
        RawFrameId { hash_id, team_id }
    }

    pub fn to_full(&self, part: i32) -> FrameId {
        FrameId {
            hash_id: self.hash_id.clone(),
            team_id: self.team_id,
            part,
        }
    }
}

#[derive(Debug, Clone, Hash, Eq, PartialEq)]
pub struct FrameId {
    pub hash_id: String,
    pub team_id: i32,
    pub part: i32,
}

impl Serialize for FrameId {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        let s = format!("{}/{}", self.hash_id, self.part);
        serializer.serialize_str(&s)
    }
}

impl<'de> Deserialize<'de> for FrameId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let s = String::deserialize(deserializer)?;
        let parts: Vec<&str> = s.split('/').collect();

        let hash_id = parts[0].to_string();
        let part = if parts.len() > 1 {
            parts[1].parse::<i32>().map_err(serde::de::Error::custom)?
        } else {
            0
        };

        // Frame ID's are deserialized without a Team ID. We could encode this in the type system,
        // e.g. have a "TeamlessFrameId" or something, and in fact I'd recommend that as a piece of
        // future work - Take the `Frame` struct, make it generic across the ID type, and then write
        // various impls and code. A good onboarding task maybe, for someone rusty. An alternative
        // would be to move the team_id up a level in whatever struct is using it, but it would
        // be a lot less clean.
        //
        // The reason we don't serialize FrameID's as a struct, but instead as a string, is mostly
        // down to legacy - at one point, FrameIDs were "raw_id"'s, a pure string, and their only
        // purpose was to encode be a hash of a raw frames contents, so we could rapidly look up
        // resolved frames on the basis of raw ones. Over time, I realised we almost always need
        // the team_id whenever we use the raw_id in code - when deduplicating resolution futures, when
        // putting data into caches, and when storing in the DB, so I added it to the ID - this is
        // the "RawFrameID" above. When serializing this, I just included the raw_id, but not the
        // team_id, since it was mostly used on the frontend, where team ID information is always
        // globally available (api requests are scoped by team_id, etc).
        //
        // Once we adopted Java, it became apparent we also needed to include a bit of information about
        // the output frame - the mapping of input:output frames was no longer 1:1, and since the rest
        // of the system (in particular the frontend) relied on a simple string ID, we decided to go
        // with encoding this as a suffix to the existing raw_id when serializing. In the DB and
        // the app backend, we transparently map between this suffix format and a full struct, so the
        // frontend, query runners and any user queries that are using the frame's "raw_id" (called
        // that despite including the resolved frames identifier too) don't break.

        Ok(FrameId {
            hash_id,
            team_id: 0,
            part,
        })
    }
}

impl std::fmt::Display for FrameId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}/{}", self.hash_id, self.part)
    }
}

impl FrameId {
    pub fn new(hash_id: String, team_id: i32, part: i32) -> Self {
        FrameId {
            hash_id,
            team_id,
            part,
        }
    }

    pub fn placeholder() -> Self {
        FrameId {
            hash_id: "placeholder".to_string(),
            team_id: 0,
            part: 0,
        }
    }

    pub fn to_raw(self) -> RawFrameId {
        RawFrameId::new(self.hash_id, self.team_id)
    }
}

// We emit a single, unified representation of a frame, which is what we pass on to users.
#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct FrameData {
    #[serde(rename = "raw_id")]
    pub frame_id: FrameId,
    pub mangled_name: String, // Mangled name of the function
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<u32>, // Line the function is define on, if known
    #[serde(skip_serializing_if = "Option::is_none")]
    pub column: Option<u32>, // Column the function is defined on, if known
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>, // Generally, the file the function is defined in
    pub in_app: bool,         // We hard-require clients to tell us this?
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resolved_name: Option<String>, // The name of the function, after symbolification
    pub lang: String,         // The language of the frame. Always known (I guess?)
    pub resolved: bool,       // Did we manage to resolve the frame?

    #[serde(default)] // Defaults to false
    pub synthetic: bool, // Some SDKs construct stack traces, or partially reconstruct them. This flag indicates whether the frame is synthetic or not.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub code_variables: Option<serde_json::Value>, // Variables and their values used in the code within that frame context
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json;

    #[test]
    fn test_frame_id_serialize() {
        let frame_id = FrameId::new("abc123".to_string(), 42, 5);
        let serialized = serde_json::to_string(&frame_id).unwrap();
        assert_eq!(serialized, "\"abc123/5\"");
    }

    #[test]
    fn test_frame_id_serialize_zero_index() {
        let frame_id = FrameId::new("xyz789".to_string(), 42, 0);
        let serialized = serde_json::to_string(&frame_id).unwrap();
        assert_eq!(serialized, "\"xyz789/0\"");
    }

    #[test]
    fn test_frame_id_deserialize_with_part() {
        let json = "\"abc123/5\"";
        let frame_id: FrameId = serde_json::from_str(json).unwrap();
        assert_eq!(frame_id.hash_id, "abc123");
        assert_eq!(frame_id.part, 5);
        assert_eq!(frame_id.team_id, 0); // defaults to 0
    }

    #[test]
    fn test_frame_id_deserialize_without_part() {
        let json = "\"abc123\"";
        let frame_id: FrameId = serde_json::from_str(json).unwrap();
        assert_eq!(frame_id.hash_id, "abc123");
        assert_eq!(frame_id.part, 0); // defaults to 0
        assert_eq!(frame_id.team_id, 0);
    }

    #[test]
    fn test_frame_id_round_trip() {
        let original = FrameId::new("test_hash".to_string(), 99, 3);
        let serialized = serde_json::to_string(&original).unwrap();
        let deserialized: FrameId = serde_json::from_str(&serialized).unwrap();

        assert_eq!(original.hash_id, deserialized.hash_id);
        assert_eq!(original.part, deserialized.part);
        // Note: team_id is not preserved through serialization
    }
}
