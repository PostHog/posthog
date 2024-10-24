use crate::{
    error::Error,
    metric_consts::ERRORS,
    types::{frames::Frame, Exception},
};
use reqwest::Url;
use sha2::{Digest, Sha256};

// Given resolved Frames vector and the original Exception, we can now generate a fingerprint for it
pub fn generate_fingerprint(
    exception: &Exception,
    mut frames: Vec<Frame>,
) -> Result<String, Error> {
    let mut fingerprint = format!(
        "{}-{}",
        exception.exception_type, exception.exception_message
    );

    let has_resolved_frames: bool = frames.iter().any(|f| f.resolved);
    if has_resolved_frames {
        frames.retain(|f| f.resolved);
    }

    let has_in_app_frames: bool = frames.iter().any(|f| f.in_app);
    if has_in_app_frames {
        frames.retain(|f| f.in_app);
    } else {
        metrics::counter!(ERRORS, "cause" => "no_in_app_frames").increment(1);
        frames = frames.into_iter().take(1).collect()
    }

    for frame in frames {
        let source_fn = match Url::parse(&frame.source.unwrap_or("".to_string())) {
            Ok(url) => url.path().to_string(),
            Err(_) => "unknown".to_string(),
        };

        fingerprint.push('-');
        fingerprint.push_str(&source_fn);
        fingerprint.push(':');
        fingerprint.push_str(&frame.resolved_name.unwrap_or(frame.mangled_name));
    }
    // TODO: Handle anonymous functions somehow? Not sure if these would have a resolved name at all. How would they show up
    // as unresolved names?

    Ok(fingerprint)
}

// Generate sha256 hash of the fingerprint to get a unique fingerprint identifier
pub fn hash_fingerprint(fingerprint: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(fingerprint.as_bytes());
    let result = hasher.finalize();
    format!("{:x}", result)
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn test_fingerprint_generation() {
        let exception = Exception {
            exception_type: "TypeError".to_string(),
            exception_message: "Cannot read property 'foo' of undefined".to_string(),
            mechanism: Default::default(),
            module: Default::default(),
            thread_id: None,
            stacktrace: Default::default(),
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
                lang: "javascript".to_string(),
            },
        ];

        let fingerprint = super::generate_fingerprint(&exception, resolved_frames).unwrap();
        assert_eq!(
            fingerprint,
            "TypeError-Cannot read property 'foo' of undefined-/alpha/foo.js:bar-/bar.js:baz-unknown:xyz"
        );
    }

    #[test]
    fn test_some_resolved_frames() {
        let exception = Exception {
            exception_type: "TypeError".to_string(),
            exception_message: "Cannot read property 'foo' of undefined".to_string(),
            mechanism: Default::default(),
            module: Default::default(),
            thread_id: None,
            stacktrace: Default::default(),
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
                lang: "javascript".to_string(),
            },
        ];

        let fingerprint = super::generate_fingerprint(&exception, resolved_frames).unwrap();
        assert_eq!(
            fingerprint,
            "TypeError-Cannot read property 'foo' of undefined-/alpha/foo.js:bar-/bar.js:baz"
        );
    }

    #[test]
    fn test_no_resolved_frames() {
        let exception = Exception {
            exception_type: "TypeError".to_string(),
            exception_message: "Cannot read property 'foo' of undefined".to_string(),
            mechanism: Default::default(),
            module: Default::default(),
            thread_id: None,
            stacktrace: Default::default(),
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
                lang: "javascript".to_string(),
            },
        ];

        let fingerprint = super::generate_fingerprint(&exception, resolved_frames).unwrap();
        assert_eq!(
            fingerprint,
            "TypeError-Cannot read property 'foo' of undefined-/alpha/foo.js:bar-/bar.js:baz-unknown:xyz"
        );
    }

    #[test]
    fn test_no_in_app_frames() {
        let exception = Exception {
            exception_type: "TypeError".to_string(),
            exception_message: "Cannot read property 'foo' of undefined".to_string(),
            mechanism: Default::default(),
            module: Default::default(),
            thread_id: None,
            stacktrace: Default::default(),
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
                lang: "javascript".to_string(),
            },
        ];

        let fingerprint = super::generate_fingerprint(&exception, resolved_frames).unwrap();
        assert_eq!(
            fingerprint,
            "TypeError-Cannot read property 'foo' of undefined-/alpha/foo.js:bar"
        );
    }
}
