use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use cymbal_domain::ReleaseRecord;
use cymbal_symbol_store::UnhandledError;
use cymbal_symbolication::{apple::AppleDebugImage, Frame, RawFrame};

use crate::ResolutionDeps;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResolutionExceptionProperties {
    #[serde(rename = "$exception_list")]
    pub exception_list: ResolutionExceptionList,
    #[serde(
        rename = "$debug_images",
        default,
        skip_serializing_if = "Vec::is_empty"
    )]
    pub debug_images: Vec<AppleDebugImage>,
    #[serde(flatten)]
    pub props: Map<String, Value>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ResolutionExceptionList(pub Vec<ResolutionException>);

impl ResolutionExceptionList {
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn get_release_map(&self) -> Map<String, Value> {
        ReleaseRecord::collect_to_map(
            self.0
                .iter()
                .filter_map(|exception| match &exception.stack {
                    Some(ResolutionStacktrace::Resolved { frames, .. }) => Some(frames.as_slice()),
                    _ => None,
                })
                .flatten()
                .filter_map(|frame| frame.release.as_ref()),
        )
        .into_iter()
        .filter_map(|(key, release)| serde_json::to_value(release).ok().map(|value| (key, value)))
        .collect()
    }
}

impl From<Vec<ResolutionException>> for ResolutionExceptionList {
    fn from(value: Vec<ResolutionException>) -> Self {
        Self(value)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResolutionException {
    #[serde(rename = "type", default)]
    pub exception_type: String,
    #[serde(rename = "value", default)]
    pub exception_message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub module: Option<String>,
    #[serde(rename = "stacktrace", skip_serializing_if = "Option::is_none")]
    pub stack: Option<ResolutionStacktrace>,
    #[serde(flatten)]
    pub other: Map<String, Value>,
}

impl ResolutionException {
    pub fn raw_frames(&self) -> &[RawFrame] {
        match &self.stack {
            Some(ResolutionStacktrace::Raw { frames, .. }) => frames,
            _ => &[],
        }
    }

    pub fn first_raw_frame(&self) -> Option<&RawFrame> {
        self.raw_frames().first()
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(untagged)]
pub enum ResolutionStacktrace {
    Raw {
        #[serde(rename = "type")]
        stack_type: StacktraceType,
        frames: Vec<RawFrame>,
        #[serde(flatten)]
        other: Map<String, Value>,
    },
    Resolved {
        #[serde(rename = "type")]
        stack_type: StacktraceType,
        frames: Vec<Frame>,
        #[serde(flatten)]
        other: Map<String, Value>,
    },
    Other(Value),
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum StacktraceType {
    Raw,
    Resolved,
}

impl<'de> Deserialize<'de> for ResolutionStacktrace {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let value = Value::deserialize(deserializer)?;
        let Some(object) = value.as_object() else {
            return Ok(Self::Other(value));
        };

        let mut other = object.clone();
        let stack_type = other.remove("type");
        let frames = other.remove("frames");
        let Some(Value::Array(frame_values)) = frames else {
            return Ok(Self::Other(Value::Object(object.clone())));
        };

        let explicit_raw = stack_type.as_ref().and_then(Value::as_str) == Some("raw");
        let explicit_resolved = stack_type.as_ref().and_then(Value::as_str) == Some("resolved");

        if explicit_raw || !explicit_resolved {
            let raw_frames: Result<Vec<RawFrame>, _> = frame_values
                .iter()
                .cloned()
                .map(serde_json::from_value)
                .collect();
            if let Ok(frames) = raw_frames {
                return Ok(Self::Raw {
                    stack_type: StacktraceType::Raw,
                    frames,
                    other,
                });
            }
        }

        if explicit_resolved {
            let resolved_frames: Result<Vec<Frame>, _> = frame_values
                .iter()
                .cloned()
                .map(serde_json::from_value)
                .collect();
            if let Ok(frames) = resolved_frames {
                return Ok(Self::Resolved {
                    stack_type: StacktraceType::Resolved,
                    frames,
                    other,
                });
            }
        }

        Ok(Self::Other(Value::Object(object.clone())))
    }
}

#[derive(Clone, Default)]
pub struct ExceptionResolver;

impl ExceptionResolver {
    pub fn is_java_exception(exception: &ResolutionException) -> bool {
        matches!(exception.first_raw_frame(), Some(RawFrame::Java(_))) && exception.module.is_some()
    }

    pub fn is_dart_exception(exception: &ResolutionException) -> bool {
        exception.exception_type.starts_with("minified:")
    }

    pub async fn resolve_exception_list(
        team_id: i32,
        list: ResolutionExceptionList,
        deps: ResolutionDeps,
    ) -> Result<ResolutionExceptionList, UnhandledError> {
        let mut resolved = Vec::with_capacity(list.0.len());
        for exception in list.0 {
            resolved.push(Self::resolve_exception(team_id, exception, deps.clone()).await?);
        }
        Ok(resolved.into())
    }

    pub async fn resolve_exception(
        team_id: i32,
        exception: ResolutionException,
        deps: ResolutionDeps,
    ) -> Result<ResolutionException, UnhandledError> {
        if Self::is_java_exception(&exception) {
            let _permit = deps.acquire_symbol_resolution_permit().await?;
            return deps
                .symbol_resolver
                .resolve_java_exception(team_id, exception)
                .await;
        }

        if Self::is_dart_exception(&exception) {
            let _permit = deps.acquire_symbol_resolution_permit().await?;
            return deps
                .symbol_resolver
                .resolve_dart_exception(team_id, exception)
                .await;
        }

        Ok(exception)
    }
}
