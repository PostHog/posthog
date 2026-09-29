use std::collections::HashMap;

use crate::frames::RawFrame;
use crate::types::{ExceptionList, Stacktrace};

/// The runtime paths (`abs_path`) of the Python, Ruby and PHP raw frames of one event, keyed by
/// frame content hash.
///
/// Remote resolution replaces raw frames with resolved ones, which carry the same hash in their
/// frame id, so the paths can be put back afterwards. The frame cache is keyed by that hash and
/// ignores `abs_path`, so the path must come from this event and never from a cached frame.
#[derive(Default)]
pub struct RawPaths(HashMap<String, String>);

impl RawPaths {
    pub fn collect(exceptions: &ExceptionList) -> Self {
        let mut paths = HashMap::new();
        for exception in exceptions.iter() {
            for frame in exception.get_raw_frame() {
                let (hash, path) = match frame {
                    RawFrame::Python(raw) => (raw.frame_id(), raw.path.as_ref()),
                    RawFrame::Ruby(raw) => (raw.frame_id(), raw.path.as_ref()),
                    RawFrame::Php(raw) => (raw.frame_id(), raw.path.as_ref()),
                    _ => continue,
                };
                if let Some(path) = path {
                    paths.insert(hash, path.clone());
                }
            }
        }
        Self(paths)
    }

    pub fn attach(&self, exceptions: &mut ExceptionList) {
        if self.0.is_empty() {
            return;
        }
        for exception in exceptions.iter_mut() {
            if let Some(Stacktrace::Resolved { frames }) = &mut exception.stack {
                for frame in frames {
                    frame.raw_path = self.0.get(&frame.frame_id.hash_id).cloned();
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;
    use crate::frames::Frame;
    use crate::types::Exception;

    fn raw_python(abs_path: &str) -> RawFrame {
        serde_json::from_value(json!({
            "platform": "python",
            "filename": "orders/views.py",
            "function": "create",
            "lineno": 3,
            "abs_path": abs_path,
            "in_app": true,
        }))
        .unwrap()
    }

    fn exceptions(stack: Stacktrace) -> ExceptionList {
        vec![Exception {
            exception_id: None,
            exception_type: "ValueError".to_string(),
            exception_message: "boom".to_string(),
            mechanism: None,
            module: None,
            thread_id: None,
            stack: Some(stack),
        }]
        .into()
    }

    #[test]
    fn events_sharing_a_cached_frame_keep_their_own_raw_path() {
        let first = raw_python("/srv/releases/1/acme_api/orders/views.py");
        let second = raw_python("/srv/releases/2/acme_api/orders/views.py");
        // The frame cache returns the same resolved frame to both events, because the frame id
        // ignores abs_path.
        let cached: Frame = serde_json::from_value(json!({
            "raw_id": format!("{}/0", first.raw_id(7, &[]).hash_id),
            "mangled_name": "create",
            "in_app": true,
            "resolved": true,
            "lang": "python",
            "source": "orders/views.py",
        }))
        .unwrap();

        let mut paths = Vec::new();
        for raw in [first, second] {
            let collected = RawPaths::collect(&exceptions(Stacktrace::Raw { frames: vec![raw] }));
            let mut resolved = exceptions(Stacktrace::Resolved {
                frames: vec![cached.clone()],
            });
            collected.attach(&mut resolved);
            let Some(Stacktrace::Resolved { frames }) = &resolved[0].stack else {
                unreachable!()
            };
            paths.push(frames[0].raw_path.clone());
        }

        assert_eq!(
            paths,
            vec![
                Some("/srv/releases/1/acme_api/orders/views.py".to_string()),
                Some("/srv/releases/2/acme_api/orders/views.py".to_string()),
            ]
        );
    }
}
