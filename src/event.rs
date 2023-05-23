use std::collections::HashMap;
use std::io::prelude::*;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use anyhow::{anyhow, Result};
use bytes::{Buf, Bytes};
use flate2::read::GzDecoder;
use uuid::Uuid;

#[derive(Deserialize, Default)]
pub enum Compression {
    #[default]
    #[serde(rename = "gzip-js")]
    GzipJs,
}

#[allow(dead_code)] // until they are used
#[derive(Deserialize, Default)]
pub struct EventQuery {
    compression: Option<Compression>,

    #[serde(alias = "ver")]
    version: Option<String>,

    #[serde(alias = "_")]
    sent_at: Option<i64>,
}

#[derive(Debug, Deserialize)]
pub struct EventFormData {
    pub data: String,
}

#[derive(Default, Debug, Deserialize, Serialize)]
pub struct Event {
    #[serde(alias = "$token", alias = "api_key")]
    pub token: Option<String>,

    pub event: String,
    pub properties: HashMap<String, Value>,
}

impl Event {
    /// We post up _at least one_ event, so when decompressiong and deserializing there
    /// could be more than one. Hence this function has to return a Vec.
    /// TODO: Use an axum extractor for this
    pub fn from_bytes(query: &EventQuery, bytes: Bytes) -> Result<Vec<Event>> {
        tracing::debug!(len = bytes.len(), "decoding new event");

        let payload = match query.compression {
            Some(Compression::GzipJs) => {
                let mut d = GzDecoder::new(bytes.reader());
                let mut s = String::new();
                d.read_to_string(&mut s)?;
                s
            }
            None => String::from_utf8(bytes.into())?,
        };

        tracing::debug!(json = payload, "decoded event data");
        if let Ok(events) = serde_json::from_str::<Vec<Event>>(&payload) {
            return Ok(events);
        }
        if let Ok(events) = serde_json::from_str::<Event>(&payload) {
            return Ok(vec![events]);
        }
        Err(anyhow!("unknown input shape"))
    }
}

#[derive(Clone, Default, Debug, Deserialize, Serialize)]
pub struct ProcessedEvent {
    pub uuid: Uuid,
    pub distinct_id: String,
    pub ip: String,
    pub site_url: String,
    pub data: String,
    pub now: String,
    pub sent_at: String,
    pub token: String,
}

#[cfg(test)]
mod tests {
    use super::Compression;
    use base64::Engine as _;
    use bytes::Bytes;

    use super::{Event, EventQuery};

    #[test]
    fn decode_bytes() {
        let horrible_blob = "H4sIAAAAAAAAA31T207cMBD9lSrikSy+5bIrVX2g4oWWUlEqBEKRY08Sg4mD4+xCEf/e8XLZBSGeEp+ZOWOfmXPxkMAS+pAskp1BtmBBLiHZTQbvBvDBwJgsHpIdh5/kp1Rffp18OcMwAtUS/GhcjwFKZjSbkYjX3q1G8AgeGA+Nu4ughqVRUIX7ATDwHcbr4IYYUJP32LyavMVAF8Kw2NuzTknbuTEsSkIIHlvTf+vhLnzdizUxgslvs2JgkKHr5U1s8VS0dZ/NZSnlW7CVfTvhs7EG+vT0JJaMygP0VQem7bDTvBAbcGV06JAkIwTBpYHV4Hx4zS1FJH+FX7IFj7A1NbZZQR2b4GFbwFlWzFjETY/XCpXRiN538yt/S9mdnm7bSa+lDCY+kOalKDJGs/msZMVuos0YTK+e62hZciHqes7LnDcpoVmTg+TAaqnKMhWUaaa4TllBoCDpJn2uYK3k87xeyFjZFHWdzxmdq5Q0IstBzRXlDMiHbM/5kgnerKfs+tFZqHAolQflvDZ9W0Evawu6wveiENVoND4s+Ami2jBGZbayn/42g3xblizX4skp4FYMYfJQoSQf8DfSjrGBVMEsoWpArpMbK1vc8ItLDG1j1SDvrZM6muBxN/Eg7U1cVFw70KmyRl13bhqjYeBGGrtuFqWTSzzF/q8tRyvV9SfxHXQLoBuidXY0ekeF+KQnNCqgHXaIy7KJBncNERk6VUFhhB33j8zv5uhQ/rCTvbq9/9seH5Pj3Bf/TsuzYf9g2j+3h9N6yZ8Vfpmx4KSguSY5S0lOqc5LmgmhidoMmOaixoFvktFKOo9kK9Nrt3rPxViWk5RwIhtJykZzXohP2DjmZ08+bnH/4B1fkUnGSp2SMmNlIYTguS5ga//eERZZTSVeD8cWPTMGeTMgHSOMpyRLGftDyUKwBV9b6Dx5vPwPzQHjFwsFAAA=";
        let decoded_horrible_blob = base64::engine::general_purpose::STANDARD
            .decode(horrible_blob)
            .unwrap();

        let bytes = Bytes::from(decoded_horrible_blob);
        let events = Event::from_bytes(
            &EventQuery {
                compression: Some(Compression::GzipJs),
                version: None,
                sent_at: None,
            },
            bytes,
        );

        assert_eq!(events.is_ok(), true);
    }
}
