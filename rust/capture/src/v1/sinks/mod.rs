pub mod constants;
pub mod event;
pub mod kafka;
pub mod sink;
pub mod types;

use std::str::FromStr;

pub use event::Event;
pub use sink::Sink;
pub use types::{Destination, Outcome, SinkResult};

// ---------------------------------------------------------------------------
// SinkName
// ---------------------------------------------------------------------------

/// Identity of a v1 sink target. Adding a new sink requires a new variant
/// here plus its `as_str()`, `env_prefix()`, and `FromStr` arms.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SinkName {
    /// Primary MSK sink.
    Msk,
    /// Secondary MSK sink for upgrades, cutovers, or dual-writes.
    MskAlt,
    /// WarpStream sink for upgrades, cutovers, or dual-writes.
    Ws,
}

impl SinkName {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Msk => "msk",
            Self::MskAlt => "msk_alt",
            Self::Ws => "ws",
        }
    }

    pub fn env_prefix(&self) -> &'static str {
        match self {
            Self::Msk => "CAPTURE_V1_SINK_MSK_",
            Self::MskAlt => "CAPTURE_V1_SINK_MSK_ALT_",
            Self::Ws => "CAPTURE_V1_SINK_WS_",
        }
    }
}

impl FromStr for SinkName {
    type Err = anyhow::Error;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "msk" => Ok(Self::Msk),
            "msk_alt" => Ok(Self::MskAlt),
            "ws" => Ok(Self::Ws),
            other => Err(anyhow::anyhow!("unknown sink: {other}")),
        }
    }
}

impl std::fmt::Display for SinkName {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_valid_names() {
        assert_eq!("msk".parse::<SinkName>().unwrap(), SinkName::Msk);
        assert_eq!("msk_alt".parse::<SinkName>().unwrap(), SinkName::MskAlt);
        assert_eq!("ws".parse::<SinkName>().unwrap(), SinkName::Ws);
    }

    #[test]
    fn parse_case_insensitive() {
        assert_eq!("MSK".parse::<SinkName>().unwrap(), SinkName::Msk);
        assert_eq!("Msk_Alt".parse::<SinkName>().unwrap(), SinkName::MskAlt);
        assert_eq!("WS".parse::<SinkName>().unwrap(), SinkName::Ws);
    }

    #[test]
    fn parse_unknown_name() {
        assert!("foo".parse::<SinkName>().is_err());
        assert!("warpstream".parse::<SinkName>().is_err());
    }

    #[test]
    fn parse_empty_string() {
        assert!("".parse::<SinkName>().is_err());
    }

    #[test]
    fn env_prefix_correctness() {
        assert_eq!(SinkName::Msk.env_prefix(), "CAPTURE_V1_SINK_MSK_");
        assert_eq!(SinkName::MskAlt.env_prefix(), "CAPTURE_V1_SINK_MSK_ALT_");
        assert_eq!(SinkName::Ws.env_prefix(), "CAPTURE_V1_SINK_WS_");
    }

    #[test]
    fn as_str_round_trip() {
        for name in [SinkName::Msk, SinkName::MskAlt, SinkName::Ws] {
            let parsed: SinkName = name.as_str().parse().unwrap();
            assert_eq!(parsed, name);
        }
    }
}
