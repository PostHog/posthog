use serde::{Deserialize, Serialize};

use crate::{
    error::{ResolveError, UnhandledError},
    frames::{Frame, RawFrame},
    langs::{apple::AppleDebugImage, java::RawJavaFrame},
    stages::resolution::symbol::SymbolResolver,
    types::{exception_properties::ExceptionProperties, Exception, Stacktrace},
};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResolveBatchRequest {
    pub tasks: Vec<ResolveTask>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResolveBatchResponse {
    pub results: Vec<ResolveTaskResult>,
}

/// Contract for a distributable resolution task.
/// Adding a new task variant requires implementing this trait,
/// which ensures the routing metadata and execution logic are co-located.
pub trait TaskExecutor {
    fn task_id(&self) -> u64;
    fn team_id(&self) -> i32;
    fn task_type_label(&self) -> &'static str;
    fn routing_ref(&self) -> Option<&str>;
    fn execute(
        &self,
        resolver: &dyn SymbolResolver,
    ) -> impl std::future::Future<Output = Result<ResolveTaskResult, UnhandledError>> + Send;
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ResolveTask {
    Frame(FrameTask),
    JavaException(JavaExceptionTask),
    DartException(DartExceptionTask),
}

macro_rules! delegate {
    ($self:ident, $method:ident $(, $arg:expr)*) => {
        match $self {
            ResolveTask::Frame(t) => t.$method($($arg),*),
            ResolveTask::JavaException(t) => t.$method($($arg),*),
            ResolveTask::DartException(t) => t.$method($($arg),*),
        }
    };
}

impl ResolveTask {
    pub fn task_id(&self) -> u64 {
        delegate!(self, task_id)
    }
    pub fn team_id(&self) -> i32 {
        delegate!(self, team_id)
    }
    pub fn task_type_label(&self) -> &'static str {
        delegate!(self, task_type_label)
    }
    pub fn routing_ref(&self) -> Option<&str> {
        delegate!(self, routing_ref)
    }

    pub async fn execute(
        &self,
        resolver: &dyn SymbolResolver,
    ) -> Result<ResolveTaskResult, UnhandledError> {
        match self {
            ResolveTask::Frame(t) => t.execute(resolver).await,
            ResolveTask::JavaException(t) => t.execute(resolver).await,
            ResolveTask::DartException(t) => t.execute(resolver).await,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FrameTask {
    pub task_id: u64,
    pub team_id: i32,
    pub frame: RawFrame,
    pub apple_debug_image: Option<AppleDebugImage>,
    /// Used only by the local routing planner — intentionally not sent over the wire.
    #[serde(skip)]
    pub routing_ref: Option<String>,
}

impl TaskExecutor for FrameTask {
    fn task_id(&self) -> u64 {
        self.task_id
    }

    fn team_id(&self) -> i32 {
        self.team_id
    }

    fn task_type_label(&self) -> &'static str {
        match self.frame {
            RawFrame::Apple(_) => "apple_frame",
            _ => "frame",
        }
    }

    fn routing_ref(&self) -> Option<&str> {
        self.routing_ref.as_deref()
    }

    async fn execute(
        &self,
        resolver: &dyn SymbolResolver,
    ) -> Result<ResolveTaskResult, UnhandledError> {
        let debug_images: Vec<_> = self.apple_debug_image.clone().into_iter().collect();
        let frames = resolver
            .resolve_raw_frame(self.team_id, &self.frame, &debug_images)
            .await?;
        Ok(ResolveTaskResult::Frame {
            task_id: self.task_id,
            frames,
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JavaExceptionTask {
    pub task_id: u64,
    pub team_id: i32,
    pub module: String,
    pub exception_type: String,
    pub java_frame: RawJavaFrame,
    /// Used only by the local routing planner — intentionally not sent over the wire.
    #[serde(skip)]
    pub routing_ref: Option<String>,
}

impl TaskExecutor for JavaExceptionTask {
    fn task_id(&self) -> u64 {
        self.task_id
    }

    fn team_id(&self) -> i32 {
        self.team_id
    }

    fn task_type_label(&self) -> &'static str {
        "java_exception"
    }

    fn routing_ref(&self) -> Option<&str> {
        self.routing_ref.as_deref()
    }

    async fn execute(
        &self,
        resolver: &dyn SymbolResolver,
    ) -> Result<ResolveTaskResult, UnhandledError> {
        let exception = Exception {
            exception_id: None,
            exception_type: self.exception_type.clone(),
            exception_message: String::new(),
            mechanism: None,
            module: Some(self.module.clone()),
            thread_id: None,
            stack: Some(Stacktrace::Raw {
                frames: vec![RawFrame::Java(self.java_frame.clone())],
            }),
        };
        let resolved = resolver
            .resolve_java_exception(self.team_id, exception)
            .await?;
        Ok(ResolveTaskResult::JavaException {
            task_id: self.task_id,
            module: resolved.module,
            exception_type: resolved.exception_type,
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DartExceptionTask {
    pub task_id: u64,
    pub team_id: i32,
    pub exception_type: String,
    pub chunk_id: String,
    /// Used only by the local routing planner — intentionally not sent over the wire.
    #[serde(skip)]
    pub routing_ref: Option<String>,
}

impl TaskExecutor for DartExceptionTask {
    fn task_id(&self) -> u64 {
        self.task_id
    }

    fn team_id(&self) -> i32 {
        self.team_id
    }

    fn task_type_label(&self) -> &'static str {
        "dart_exception"
    }

    fn routing_ref(&self) -> Option<&str> {
        self.routing_ref.as_deref()
    }

    async fn execute(
        &self,
        resolver: &dyn SymbolResolver,
    ) -> Result<ResolveTaskResult, UnhandledError> {
        let exception_type = match resolver
            .resolve_dart_minified_name(self.team_id, self.chunk_id.clone(), &self.exception_type)
            .await
        {
            Ok(value) => value,
            Err(ResolveError::ResolutionError(_)) => self.exception_type.clone(),
            Err(ResolveError::UnhandledError(err)) => return Err(err),
        };
        Ok(ResolveTaskResult::DartException {
            task_id: self.task_id,
            exception_type,
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ResolveTaskResult {
    Frame {
        task_id: u64,
        frames: Vec<Frame>,
    },
    JavaException {
        task_id: u64,
        module: Option<String>,
        exception_type: String,
    },
    DartException {
        task_id: u64,
        exception_type: String,
    },
}

impl ResolveTaskResult {
    pub fn task_id(&self) -> u64 {
        match self {
            ResolveTaskResult::Frame { task_id, .. }
            | ResolveTaskResult::JavaException { task_id, .. }
            | ResolveTaskResult::DartException { task_id, .. } => *task_id,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct TaskLocation {
    pub exception_index: usize,
    pub frame_index: Option<usize>,
}

#[derive(Debug, Clone)]
pub struct PlannedTask {
    pub task: ResolveTask,
    pub location: TaskLocation,
}

pub fn extract_tasks(event: &ExceptionProperties, next_task_id: &mut u64) -> Vec<PlannedTask> {
    let mut tasks = Vec::new();

    for (exception_index, exception) in event.exception_list.iter().enumerate() {
        if let Some(java_task) = build_java_exception_task(event.team_id, exception, next_task_id) {
            tasks.push(PlannedTask {
                task: ResolveTask::JavaException(java_task),
                location: TaskLocation {
                    exception_index,
                    frame_index: None,
                },
            });
        }

        if let Some(dart_task) = build_dart_exception_task(event.team_id, exception, next_task_id) {
            tasks.push(PlannedTask {
                task: ResolveTask::DartException(dart_task),
                location: TaskLocation {
                    exception_index,
                    frame_index: None,
                },
            });
        }

        let Some(Stacktrace::Raw { frames }) = &exception.stack else {
            continue;
        };

        for (frame_index, frame) in frames.iter().enumerate() {
            let (routing_ref, apple_debug_image) = match frame {
                RawFrame::Apple(apple_frame) => {
                    let debug_image = apple_frame.matching_debug_image(&event.debug_images);
                    let routing_ref = debug_image.as_ref().map(|image| image.debug_id.clone());
                    (routing_ref, debug_image)
                }
                _ => (frame.symbol_set_ref(), None),
            };

            let task = FrameTask {
                task_id: next_id(next_task_id),
                team_id: event.team_id,
                frame: frame.clone(),
                apple_debug_image,
                routing_ref,
            };

            tasks.push(PlannedTask {
                task: ResolveTask::Frame(task),
                location: TaskLocation {
                    exception_index,
                    frame_index: Some(frame_index),
                },
            });
        }
    }

    tasks
}

fn build_java_exception_task(
    team_id: i32,
    exception: &crate::types::Exception,
    next_task_id: &mut u64,
) -> Option<JavaExceptionTask> {
    let module = exception.module.clone()?;

    let Some(RawFrame::Java(java_frame)) = exception.get_first_raw_frame() else {
        return None;
    };

    Some(JavaExceptionTask {
        task_id: next_id(next_task_id),
        team_id,
        module,
        exception_type: exception.exception_type.clone(),
        java_frame: java_frame.clone(),
        routing_ref: java_frame.symbol_set_ref(),
    })
}

fn build_dart_exception_task(
    team_id: i32,
    exception: &crate::types::Exception,
    next_task_id: &mut u64,
) -> Option<DartExceptionTask> {
    if !exception.exception_type.starts_with("minified:") {
        return None;
    }

    let chunk_id = exception
        .get_raw_frame()
        .iter()
        .find_map(|frame| match frame {
            RawFrame::JavaScriptWeb(js_frame) => js_frame.chunk_id.clone(),
            RawFrame::JavaScriptNode(node_frame) => node_frame.chunk_id.clone(),
            RawFrame::LegacyJS(js_frame) => js_frame.chunk_id.clone(),
            _ => None,
        })?;

    Some(DartExceptionTask {
        task_id: next_id(next_task_id),
        team_id,
        exception_type: exception.exception_type.clone(),
        chunk_id: chunk_id.clone(),
        routing_ref: Some(chunk_id),
    })
}

fn next_id(next_task_id: &mut u64) -> u64 {
    let task_id = *next_task_id;
    *next_task_id += 1;
    task_id
}
