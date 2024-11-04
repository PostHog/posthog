use crate::{
    error::Error,
    metric_consts::ERRORS,
    types::{frames::Frame, Exception},
};
use reqwest::Url;
use sha2::{Digest, Sha512};

// Given resolved Frames vector and the original Exception, we can now generate a fingerprint for it
pub fn generate_fingerprint(
    exception: &Exception,
    mut frames: Vec<Frame>,
) -> Result<String, Error> {
    let mut hasher = Sha512::new();

    hasher.update(&exception.exception_type);
    hasher.update(&exception.exception_message);

    // only use resolved frames if any exist
    let has_resolved_frames: bool = frames.iter().any(|f| f.resolved);
    if has_resolved_frames {
        frames.retain(|f| f.resolved);
    }

    // only use in app frames if any exist, otherwise only use the first frame
    let has_in_app_frames: bool = frames.iter().any(|f| f.in_app);
    if has_in_app_frames {
        frames.retain(|f| f.in_app);
    } else {
        metrics::counter!(ERRORS, "cause" => "no_in_app_frames").increment(1);
        frames.truncate(1);
    }

    for frame in frames {
        let source_fn = match Url::parse(&frame.source.unwrap_or("".to_string())) {
            Ok(url) => url.path().to_string(),
            Err(_) => "unknown".to_string(),
        };

        hasher.update(&source_fn);
        hasher.update(frame.resolved_name.unwrap_or(frame.mangled_name));
    }
    // TODO: Handle anonymous functions somehow? Not sure if these would have a resolved name at all. How would they show up
    // as unresolved names?

    let result = hasher.finalize();

    Ok(format!("{:x}", result))
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

        let fingerprint = super::generate_fingerprint(&exception, resolved_frames).unwrap();
        assert_eq!(
            fingerprint,
            "e2a134db8585bafb19fa6c15b92bd46c699e06df7f39ce74281227e7c915adf0c997ab61757820710d85817b4a11823e57f9bcae526432c085b53e28397f3007"
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

        let fingerprint = super::generate_fingerprint(&exception, resolved_frames).unwrap();
        assert_eq!(
            fingerprint,
            "528bf82706cdcf928b3382d6bfb717c9572aa6855ffe8b620132a813dd54f2ee5c13437d22bb557634c4ceec104ce9c8c5a87d5d7cf36239be052ace8b9962aa"
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

        let fingerprint = super::generate_fingerprint(&exception, resolved_frames).unwrap();
        assert_eq!(
            fingerprint,
            "e2a134db8585bafb19fa6c15b92bd46c699e06df7f39ce74281227e7c915adf0c997ab61757820710d85817b4a11823e57f9bcae526432c085b53e28397f3007"
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

        let fingerprint = super::generate_fingerprint(&exception, resolved_frames).unwrap();
        assert_eq!(
            fingerprint,
            "c0fea2676a395a11577fd7a7b3006bcc416f6ceeb13290f831c4b5dc4de443ff51c5866d5c378137307c25cc8837cca6c82737e9704c47ed8408ff3937033e70"
        );
    }
}
