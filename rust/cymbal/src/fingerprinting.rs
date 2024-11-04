use crate::types::Exception;
use sha2::{Digest, Sha512};

// Given resolved Frames vector and the original Exception, we can now generate a fingerprint for it
pub fn generate_fingerprint(exception: &[Exception]) -> String {
    let mut hasher = Sha512::new();

    for exc in exception {
        exc.include_in_fingerprint(&mut hasher);
    }
    // TODO: Handle anonymous functions somehow? Not sure if these would have a resolved name at all. How would they show up
    // as unresolved names?

    let result = hasher.finalize();

    format!("{:x}", result)
}

#[cfg(test)]
mod test {
    use crate::types::{frames::Frame, Stacktrace};

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
            "e2a134db8585bafb19fa6c15b92bd46c699e06df7f39ce74281227e7c915adf0c997ab61757820710d85817b4a11823e57f9bcae526432c085b53e28397f3007"
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
                resolved: false,
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
            "528bf82706cdcf928b3382d6bfb717c9572aa6855ffe8b620132a813dd54f2ee5c13437d22bb557634c4ceec104ce9c8c5a87d5d7cf36239be052ace8b9962aa"
        );
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

        exception.stack = Some(Stacktrace::Resolved {
            frames: resolved_frames,
        });

        let fingerprint = super::generate_fingerprint(&[exception]);
        assert_eq!(
            fingerprint,
            "e2a134db8585bafb19fa6c15b92bd46c699e06df7f39ce74281227e7c915adf0c997ab61757820710d85817b4a11823e57f9bcae526432c085b53e28397f3007"
        );
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

        let resolved_frames = vec![
            Frame {
                mangled_name: "foo".to_string(),
                line: Some(10),
                column: Some(5),
                source: Some("http://example.com/alpha/foo.js".to_string()),
                in_app: false,
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
                in_app: false,
                resolved_name: Some("baz".to_string()),
                resolved: false,
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
            "c0fea2676a395a11577fd7a7b3006bcc416f6ceeb13290f831c4b5dc4de443ff51c5866d5c378137307c25cc8837cca6c82737e9704c47ed8408ff3937033e70"
        );
    }
}
