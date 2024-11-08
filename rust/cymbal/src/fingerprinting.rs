use crate::types::Exception;
use sha2::{Digest, Sha512};

// Given resolved Frames vector and the original Exception, we can now generate a fingerprint for it
pub fn generate_fingerprint(exception: &[Exception]) -> String {
    let mut hasher = Sha512::new();

    for exc in exception {
        exc.include_in_fingerprint(&mut hasher);
    }

    let result = hasher.finalize();

    format!("{:x}", result)
}

#[cfg(test)]
mod test {
    use crate::{frames::Frame, types::Stacktrace};

    use super::*;

    #[test]
    fn test_fingerprint_generation() {
        let mut exception = Exception {
            exception_type: "TypeError".to_string(),
            exception_message: "Cannot read property 'foo' of undefined".to_string(),
            mechanism: Default::default(),
            module: Default::default(),
            thread_id: None,
            stack: Default::default(),
        };

        let resolved_frames = vec![
            Frame {
                mangled_name: "foo".to_string(),
                line: Some(10),
                column: Some(5),
                source: Some("http://example.com/alpha/foo.js".to_string()),
                in_app: true,
                resolved_name: Some("bar".to_string()),
                resolved: true,
                resolve_failure: None,
                lang: "javascript".to_string(),
            },
            Frame {
                mangled_name: "bar".to_string(),
                line: Some(20),
                column: Some(15),
                source: Some("http://example.com/bar.js".to_string()),
                in_app: true,
                resolved_name: Some("baz".to_string()),
                resolved: true,
                resolve_failure: None,
                lang: "javascript".to_string(),
            },
            Frame {
                mangled_name: "xyz".to_string(),
                line: Some(30),
                column: Some(25),
                source: None,
                in_app: true,
                resolved_name: None,
                resolved: true,
                resolve_failure: None,
                lang: "javascript".to_string(),
            },
            Frame {
                mangled_name: "<anonymous>".to_string(),
                line: None,
                column: None,
                source: None,
                in_app: false,
                resolved_name: None,
                resolved: true,
                resolve_failure: None,
                lang: "javascript".to_string(),
            },
        ];

        exception.stack = Some(Stacktrace::Resolved {
            frames: resolved_frames,
        });

        let fingerprint = super::generate_fingerprint(&[exception]);
        assert_eq!(
            fingerprint,
            "7f5c327cd3941f2da655d852eb4661b411440c080c7ff014feb920afde68beaffe663908d4ab5fb7b7f1e7ab7f1f7cd17949139e8f812b1c3ff0911fc5b68f37"
        );
    }

    #[test]
    fn test_some_resolved_frames() {
        let mut exception = Exception {
            exception_type: "TypeError".to_string(),
            exception_message: "Cannot read property 'foo' of undefined".to_string(),
            mechanism: Default::default(),
            module: Default::default(),
            thread_id: None,
            stack: Default::default(),
        };

        let mut resolved_frames = vec![
            Frame {
                mangled_name: "foo".to_string(),
                line: Some(10),
                column: Some(5),
                source: Some("http://example.com/alpha/foo.js".to_string()),
                in_app: true,
                resolved_name: Some("bar".to_string()),
                resolved: true,
                resolve_failure: None,
                lang: "javascript".to_string(),
            },
            Frame {
                mangled_name: "bar".to_string(),
                line: Some(20),
                column: Some(15),
                source: Some("http://example.com/bar.js".to_string()),
                in_app: true,
                resolved_name: Some("baz".to_string()),
                resolved: true,
                resolve_failure: None,
                lang: "javascript".to_string(),
            },
        ];

        let unresolved_frame = Frame {
            mangled_name: "xyz".to_string(),
            line: Some(30),
            column: Some(25),
            source: None,
            in_app: true,
            resolved_name: None,
            resolved: false,
            resolve_failure: None,
            lang: "javascript".to_string(),
        };

        exception.stack = Some(Stacktrace::Resolved {
            frames: resolved_frames.clone(),
        });

        let fingerprint_with_all_resolved = super::generate_fingerprint(&[exception.clone()]);

        resolved_frames.push(unresolved_frame);
        exception.stack = Some(Stacktrace::Resolved {
            frames: resolved_frames,
        });

        let mixed_fingerprint = super::generate_fingerprint(&[exception]);

        // In cases where there are SOME resolved frames, the fingerprint should be identical
        // to the case where all frames are resolved (unresolved frames should be ignored)
        assert_eq!(fingerprint_with_all_resolved, mixed_fingerprint);
    }

    #[test]
    fn test_no_resolved_frames() {
        let mut exception = Exception {
            exception_type: "TypeError".to_string(),
            exception_message: "Cannot read property 'foo' of undefined".to_string(),
            mechanism: Default::default(),
            module: Default::default(),
            thread_id: None,
            stack: Default::default(),
        };

        let resolved_frames = vec![
            Frame {
                mangled_name: "foo".to_string(),
                line: Some(10),
                column: Some(5),
                source: Some("http://example.com/alpha/foo.js".to_string()),
                in_app: true,
                resolved_name: Some("bar".to_string()),
                resolved: false,
                resolve_failure: None,
                lang: "javascript".to_string(),
            },
            Frame {
                mangled_name: "bar".to_string(),
                line: Some(20),
                column: Some(15),
                source: Some("http://example.com/bar.js".to_string()),
                in_app: true,
                resolved_name: Some("baz".to_string()),
                resolved: false,
                resolve_failure: None,
                lang: "javascript".to_string(),
            },
            Frame {
                mangled_name: "xyz".to_string(),
                line: Some(30),
                column: Some(25),
                source: None,
                in_app: true,
                resolved_name: None,
                resolved: false,
                resolve_failure: None,
                lang: "javascript".to_string(),
            },
        ];

        let no_stack_fingerprint = super::generate_fingerprint(&[exception.clone()]);

        exception.stack = Some(Stacktrace::Resolved {
            frames: resolved_frames,
        });

        let with_stack_fingerprint = super::generate_fingerprint(&[exception]);

        // If there are NO resolved frames, fingerprinting should account for the unresolved frames
        assert_ne!(no_stack_fingerprint, with_stack_fingerprint);
    }

    #[test]
    fn test_no_in_app_frames() {
        let mut exception = Exception {
            exception_type: "TypeError".to_string(),
            exception_message: "Cannot read property 'foo' of undefined".to_string(),
            mechanism: Default::default(),
            module: Default::default(),
            thread_id: None,
            stack: Default::default(),
        };

        let mut resolved_frames = vec![Frame {
            mangled_name: "foo".to_string(),
            line: Some(10),
            column: Some(5),
            source: Some("http://example.com/alpha/foo.js".to_string()),
            in_app: true,
            resolved_name: Some("bar".to_string()),
            resolved: false,
            resolve_failure: None,
            lang: "javascript".to_string(),
        }];

        let non_app_frame = Frame {
            mangled_name: "bar".to_string(),
            line: Some(20),
            column: Some(15),
            source: Some("http://example.com/bar.js".to_string()),
            in_app: false,
            resolved_name: Some("baz".to_string()),
            resolved: false,
            resolve_failure: None,
            lang: "javascript".to_string(),
        };

        exception.stack = Some(Stacktrace::Resolved {
            frames: resolved_frames.clone(),
        });

        let fingerprint_1 = super::generate_fingerprint(&[exception.clone()]);

        resolved_frames.push(non_app_frame);
        exception.stack = Some(Stacktrace::Resolved {
            frames: resolved_frames,
        });

        let fingerprint_2 = super::generate_fingerprint(&[exception]);

        // Fingerprinting should ignore non-in-app frames
        assert_eq!(fingerprint_1, fingerprint_2);
    }
}
