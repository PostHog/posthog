use crate::{
    error::Error,
    types::{frames::Frame, Exception},
};
use reqwest::Url;
use sha2::{Digest, Sha256};

// Given resolved Frames vector and the original Exception, we can now generate a fingerprint for it
pub fn generate_fingerprint(
    exception: &Exception,
    resolved_frames: Vec<Frame>,
) -> Result<String, Error> {
    let mut fingerprint = format!(
        "{}-{}",
        exception.exception_type, exception.exception_message
    );
    for frame in resolved_frames {
        if !frame.in_app {
            // We only want to fingerprint in-app frames
            // TODO: What happens if we don't have any in-app frames? The lowest level frame should at least be in app
            // - this can only happen when there's some bug in our stack trace collection?
            continue;
        }

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
                lang: "javascript".to_string(),
            },
            Frame {
                mangled_name: "bar".to_string(),
                line: Some(20),
                column: Some(15),
                source: Some("http://example.com/bar.js".to_string()),
                in_app: true,
                resolved_name: Some("baz".to_string()),
                lang: "javascript".to_string(),
            },
            Frame {
                mangled_name: "xyz".to_string(),
                line: Some(30),
                column: Some(25),
                source: None,
                in_app: true,
                resolved_name: None,
                lang: "javascript".to_string(),
            },
            Frame {
                mangled_name: "<anonymous>".to_string(),
                line: None,
                column: None,
                source: None,
                in_app: false,
                resolved_name: None,
                lang: "javascript".to_string(),
            },
        ];

        let fingerprint = super::generate_fingerprint(&exception, resolved_frames).unwrap();
        assert_eq!(
            fingerprint,
            "TypeError-Cannot read property 'foo' of undefined-/alpha/foo.js:bar-/bar.js:baz-unknown:xyz"
        );
    }
}
