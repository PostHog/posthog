use crate::{
    assignment_rules::NewAssignment,
    error::UnhandledError,
    teams::TeamManager,
    types::{Exception, RawErrProps},
};
use common_types::TeamId;
use grouping_rules::{try_grouping_rules, GroupingRule};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};
use sqlx::PgConnection;
use uuid::Uuid;

pub mod grouping_rules;

pub async fn resolve_fingerprint(
    conn: &mut PgConnection,
    team_manager: &TeamManager,
    team_id: TeamId,
    props: &RawErrProps,
) -> Result<Fingerprint, UnhandledError> {
    if let Some(rule) = try_grouping_rules(conn, team_id, team_manager, props).await? {
        Ok(Fingerprint::from_rule(rule))
    } else {
        Ok(generate_fingerprint(&props.exception_list))
    }
}

pub fn generate_fingerprint(exceptions: &[Exception]) -> Fingerprint {
    let mut fingerprint = FingerprintBuilder::default();

    for exc in exceptions.iter() {
        exc.include_in_fingerprint(&mut fingerprint);
    }

    fingerprint.finalize()
}

// We put a vec of these on the event as a record of what actually went into a fingerprint.
// This data is user-facing/used in the frontend, so make changes with caution
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "type")]
pub enum FingerprintRecordPart {
    Frame {
        raw_id: String,
        pieces: Vec<String>,
    },
    Exception {
        id: Option<String>,
        pieces: Vec<String>,
    },
    Custom {
        rule_id: Uuid,
    },
    Manual,
}

// Anything that can be included in a fingerprint should implement this
pub trait FingerprintComponent {
    fn update(&self, fingerprint: &mut FingerprintBuilder);
}

#[derive(Debug, Clone)]
pub struct Fingerprint {
    pub value: String,
    pub record: Vec<FingerprintRecordPart>,
    pub assignment: Option<NewAssignment>, // If this fingerprint came from a custom rule, it might carry an assignment with it
}

#[derive(Debug, Clone, Default)]
pub struct FingerprintBuilder {
    pub record: Vec<FingerprintRecordPart>,
    pub hasher: Sha512,
}

impl FingerprintBuilder {
    pub fn update(&mut self, data: impl AsRef<[u8]>) {
        self.hasher.update(data);
    }

    pub fn add_part(&mut self, part: impl Into<FingerprintRecordPart>) {
        self.record.push(part.into());
    }

    pub fn finalize(self) -> Fingerprint {
        let result = self.hasher.finalize();
        let content = format!("{result:x}");
        Fingerprint {
            value: content,
            record: self.record,
            assignment: None,
        }
    }
}

impl Fingerprint {
    pub fn from_rule(rule: GroupingRule) -> Self {
        let content = format!("custom-rule:{}", rule.id);
        Fingerprint {
            value: content,
            record: vec![FingerprintRecordPart::Custom { rule_id: rule.id }],
            assignment: rule.assignment(),
        }
    }
}

#[cfg(test)]
mod test {

    use crate::{frames::Frame, types::Stacktrace};
    use common_types::error_tracking::FrameId;
    use uuid::Uuid;

    use super::*;

    #[test]
    fn test_some_resolved_frames() {
        let team_id = 1;
        let mut exception = Exception {
            exception_id: None,
            exception_type: "TypeError".to_string(),
            exception_message: "Cannot read property 'foo' of undefined".to_string(),
            mechanism: Default::default(),
            module: Default::default(),
            thread_id: None,
            stack: Default::default(),
        };

        let mut resolved_frames = vec![
            Frame {
                raw_id: FrameId::new(String::new(), team_id, 0),
                mangled_name: "foo".to_string(),
                line: Some(10),
                column: Some(5),
                source: Some("http://example.com/alpha/foo.js".to_string()),
                in_app: true,
                resolved_name: Some("bar".to_string()),
                resolved: true,
                resolve_failure: None,
                lang: "javascript".to_string(),
                junk_drawer: None,
                context: None,
                release: None,
                synthetic: false,
                suspicious: false,
                module: None,
            },
            Frame {
                raw_id: FrameId::new(String::new(), team_id, 0),
                mangled_name: "bar".to_string(),
                line: Some(20),
                column: Some(15),
                source: Some("http://example.com/bar.js".to_string()),
                in_app: true,
                resolved_name: Some("baz".to_string()),
                resolved: true,
                resolve_failure: None,
                lang: "javascript".to_string(),
                junk_drawer: None,
                context: None,
                release: None,
                synthetic: false,
                suspicious: false,
                module: None,
            },
        ];

        let unresolved_frame = Frame {
            raw_id: FrameId::new(String::new(), team_id, 0),
            mangled_name: "xyz".to_string(),
            line: Some(30),
            column: Some(25),
            source: None,
            in_app: true,
            resolved_name: None,
            resolved: false,
            resolve_failure: None,
            lang: "javascript".to_string(),
            junk_drawer: None,
            context: None,
            release: None,
            synthetic: false,
            suspicious: false,
            module: None,
        };

        exception.stack = Some(Stacktrace::Resolved {
            frames: resolved_frames.clone(),
        });

        let fingerprint_with_all_resolved = super::generate_fingerprint(&[exception.clone()]).value;

        resolved_frames.push(unresolved_frame);
        exception.stack = Some(Stacktrace::Resolved {
            frames: resolved_frames,
        });

        let mixed_fingerprint = super::generate_fingerprint(&[exception]).value;

        // In cases where there are SOME resolved frames, the fingerprint should be identical
        // to the case where all frames are resolved (unresolved frames should be ignored)
        assert_eq!(fingerprint_with_all_resolved, mixed_fingerprint);
    }

    #[test]
    fn test_no_resolved_frames() {
        let mut exception = Exception {
            exception_id: None,
            exception_type: "TypeError".to_string(),
            exception_message: "Cannot read property 'foo' of undefined".to_string(),
            mechanism: Default::default(),
            module: Default::default(),
            thread_id: None,
            stack: Default::default(),
        };

        let resolved_frames = vec![
            Frame {
                raw_id: FrameId::new(String::new(), 1, 0),
                mangled_name: "foo".to_string(),
                line: Some(10),
                column: Some(5),
                source: Some("http://example.com/alpha/foo.js".to_string()),
                in_app: true,
                resolved_name: Some("bar".to_string()),
                resolved: false,
                resolve_failure: None,
                lang: "javascript".to_string(),
                junk_drawer: None,
                context: None,
                release: None,
                synthetic: false,
                suspicious: false,
                module: None,
            },
            Frame {
                raw_id: FrameId::new(String::new(), 1, 0),
                mangled_name: "bar".to_string(),
                line: Some(20),
                column: Some(15),
                source: Some("http://example.com/bar.js".to_string()),
                in_app: true,
                resolved_name: Some("baz".to_string()),
                resolved: false,
                resolve_failure: None,
                lang: "javascript".to_string(),
                junk_drawer: None,
                context: None,
                release: None,
                synthetic: false,
                suspicious: false,
                module: None,
            },
            Frame {
                raw_id: FrameId::new(String::new(), 1, 0),
                mangled_name: "xyz".to_string(),
                line: Some(30),
                column: Some(25),
                source: None,
                in_app: true,
                resolved_name: None,
                resolved: false,
                resolve_failure: None,
                lang: "javascript".to_string(),
                junk_drawer: None,
                context: None,
                release: None,
                synthetic: false,
                suspicious: false,
                module: None,
            },
        ];

        let no_stack_fingerprint = super::generate_fingerprint(&[exception.clone()]).value;

        exception.stack = Some(Stacktrace::Resolved {
            frames: resolved_frames,
        });

        let with_stack_fingerprint = super::generate_fingerprint(&[exception]).value;

        // If there are NO resolved frames, fingerprinting should account for the unresolved frames
        assert_ne!(no_stack_fingerprint, with_stack_fingerprint);
    }

    #[test]
    fn test_no_in_app_frames() {
        let mut exception = Exception {
            exception_id: Some(Uuid::now_v7().to_string()),
            exception_type: "TypeError".to_string(),
            exception_message: "Cannot read property 'foo' of undefined".to_string(),
            mechanism: Default::default(),
            module: Default::default(),
            thread_id: None,
            stack: Default::default(),
        };

        let mut resolved_frames = vec![Frame {
            raw_id: FrameId::new(String::new(), 1, 0),
            mangled_name: "foo".to_string(),
            line: Some(10),
            column: Some(5),
            source: Some("http://example.com/alpha/foo.js".to_string()),
            in_app: true,
            resolved_name: Some("bar".to_string()),
            resolved: false,
            resolve_failure: None,
            lang: "javascript".to_string(),
            junk_drawer: None,
            context: None,
            release: None,
            synthetic: false,
            suspicious: false,
            module: None,
        }];

        let non_app_frame = Frame {
            raw_id: FrameId::new(String::new(), 1, 0),
            mangled_name: "bar".to_string(),
            line: Some(20),
            column: Some(15),
            source: Some("http://example.com/bar.js".to_string()),
            in_app: false,
            resolved_name: Some("baz".to_string()),
            resolved: false,
            resolve_failure: None,
            lang: "javascript".to_string(),
            junk_drawer: None,
            context: None,
            release: None,
            synthetic: false,
            suspicious: false,
            module: None,
        };

        exception.stack = Some(Stacktrace::Resolved {
            frames: resolved_frames.clone(),
        });

        let fingerprint_1 = super::generate_fingerprint(&[exception.clone()]).value;

        resolved_frames.push(non_app_frame);
        exception.stack = Some(Stacktrace::Resolved {
            frames: resolved_frames,
        });

        let fingerprint_2 = super::generate_fingerprint(&[exception]).value;

        // Fingerprinting should ignore non-in-app frames
        assert_eq!(fingerprint_1, fingerprint_2);
    }
}
