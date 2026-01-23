use chrono::{DateTime, Utc};

use cyclotron_core::{
    Job, JobInit, JobState, ManagerConfig, PoolConfig, QueueManager, Worker, WorkerConfig,
};
use neon::{
    handle::Handle,
    object::Object,
    prelude::{Context, FunctionContext, ModuleContext, TaskContext},
    result::{JsResult, NeonResult},
    types::{
        buffer::TypedArray, JsArray, JsArrayBuffer, JsNull, JsNumber, JsObject, JsPromise,
        JsString, JsUint32Array, JsUint8Array, JsUndefined, JsValue,
    },
};
use once_cell::sync::OnceCell;
use serde::de::DeserializeOwned;
use serde::Deserialize;
use serde_json::Value;
use tokio::runtime::Runtime;
use uuid::Uuid;

static WORKER: OnceCell<Worker> = OnceCell::new();
static MANAGER: OnceCell<QueueManager> = OnceCell::new();
static RUNTIME: OnceCell<Runtime> = OnceCell::new();

fn runtime<'a, C: Context<'a>>(cx: &mut C) -> NeonResult<&'static Runtime> {
    RUNTIME
        .get_or_try_init(Runtime::new)
        .or_else(|e| cx.throw_error(format!("failed to create tokio runtime: {e}")))
}

// The general interface for calling our functions takes a JSON serialized stirng,
// because neon has no nice serde support for function arguments (and generally.
// rippping objects from the v8 runtime piece by piece is slower than just passing
// a since chunk of bytes). These are convenience functions for converting between
pub fn from_json_string<'a, T, C>(cx: &mut C, object: Handle<JsString>) -> NeonResult<T>
where
    T: DeserializeOwned,
    C: Context<'a>,
{
    let value: T =
        serde_json::from_str(&object.value(cx)).or_else(|e| cx.throw_error(format!("{e}")))?;
    Ok(value)
}

pub fn to_json_string<'a, T, C>(cx: &mut C, value: T) -> NeonResult<String>
where
    T: serde::Serialize,
    C: Context<'a>,
{
    let value = serde_json::to_string(&value)
        .or_else(|e| cx.throw_error(format!("failed to serialize value: {e}")))?;
    Ok(value)
}

fn hello(mut cx: FunctionContext) -> JsResult<JsString> {
    let arg1 = cx.argument::<JsString>(0)?;
    let value: Value = from_json_string(&mut cx, arg1)?;
    let string = to_json_string(&mut cx, value)?;
    Ok(cx.string(string))
}

fn init_worker_impl(mut cx: FunctionContext, throw_on_reinit: bool) -> JsResult<JsPromise> {
    let arg1 = cx.argument::<JsString>(0)?;

    let config: PoolConfig = from_json_string(&mut cx, arg1)?;

    let worker_config: WorkerConfig = if let Ok(arg2) = cx.argument::<JsString>(1) {
        from_json_string(&mut cx, arg2)?
    } else {
        Default::default()
    };

    let (deferred, promise) = cx.promise();
    let channel = cx.channel();
    let runtime = runtime(&mut cx)?;

    let fut = async move {
        let worker = Worker::new(config, worker_config).await;
        deferred.settle_with(&channel, move |mut cx| {
            if WORKER.get().is_some() && !throw_on_reinit {
                return Ok(cx.null()); // Short circuit to make using maybe_init a no-op
            }
            let worker = worker.or_else(|e| cx.throw_error(format!("{e}")))?;
            let already_set = WORKER.set(worker).is_err();
            if already_set && throw_on_reinit {
                cx.throw_error("worker already initialized")
            } else {
                Ok(cx.null())
            }
        });
    };

    runtime.spawn(fut);

    Ok(promise)
}

fn init_manager_impl(mut cx: FunctionContext, throw_on_reinit: bool) -> JsResult<JsPromise> {
    let arg1 = cx.argument::<JsString>(0)?;
    let config: ManagerConfig = from_json_string(&mut cx, arg1)?;

    let (deferred, promise) = cx.promise();
    let channel = cx.channel();
    let runtime = runtime(&mut cx)?;

    let fut = async move {
        let manager = QueueManager::new(config).await;
        deferred.settle_with(&channel, move |mut cx| {
            if MANAGER.get().is_some() && !throw_on_reinit {
                return Ok(cx.null()); // Short circuit to make using maybe_init a no-op
            }
            let manager = manager.or_else(|e| cx.throw_error(format!("{e}")))?;
            let already_set = MANAGER.set(manager).is_err();
            if already_set && throw_on_reinit {
                cx.throw_error("manager already initialized")
            } else {
                Ok(cx.null())
            }
        });
    };

    runtime.spawn(fut);

    Ok(promise)
}

fn init_worker(cx: FunctionContext) -> JsResult<JsPromise> {
    init_worker_impl(cx, true)
}

fn init_manager(cx: FunctionContext) -> JsResult<JsPromise> {
    init_manager_impl(cx, true)
}

fn maybe_init_worker(cx: FunctionContext) -> JsResult<JsPromise> {
    init_worker_impl(cx, false)
}

fn maybe_init_manager(cx: FunctionContext) -> JsResult<JsPromise> {
    init_manager_impl(cx, false)
}

// throw_error has a type signature that makes it inconvenient to use in closures, because
// it requires that you specify the V of the NeonResult<V> returned, even though it's always
// an error. This is a sane thing for it to do, but it's inconvenient for us, because we
// frequently settle promises early, before we have a V to use for type inference. This little
// wrapper makes that easier, by specifying the V as JsNull
fn throw_null_err<'c, C>(cx: &mut C, msg: &str) -> NeonResult<Handle<'c, JsNull>>
where
    C: Context<'c>,
{
    cx.throw_error(msg)
}

#[derive(Debug, Deserialize)]
pub struct JsJob {
    pub id: Option<Uuid>,
    pub team_id: i32,
    pub queue_name: String,
    pub priority: i16,
    pub scheduled: DateTime<Utc>,
    pub function_id: Option<Uuid>,
    pub vm_state: Option<String>,
    pub parameters: Option<String>,
    pub metadata: Option<String>,
}

fn create_job(mut cx: FunctionContext) -> JsResult<JsPromise> {
    let arg1: Handle<JsString> = cx.argument::<JsString>(0)?;

    let blob = cx.argument::<JsValue>(1)?;
    let blob = if blob.is_a::<JsNull, _>(&mut cx) || blob.is_a::<JsUndefined, _>(&mut cx) {
        None
    } else {
        Some(
            blob.downcast_or_throw::<JsUint8Array, _>(&mut cx)?
                .as_slice(&cx)
                .to_vec(),
        )
    };

    let js_job: JsJob = from_json_string(&mut cx, arg1)?;

    let job = js_job.to_job_init(blob);

    let (deferred, promise) = cx.promise();
    let channel = cx.channel();
    let runtime = runtime(&mut cx)?;

    let fut = async move {
        let manager = match MANAGER.get() {
            Some(manager) => manager,
            None => {
                deferred.settle_with(&channel, |mut cx| {
                    throw_null_err(&mut cx, "manager not initialized")
                });
                return;
            }
        };
        let res = manager.create_job(job).await;
        deferred.settle_with(&channel, move |mut cx| {
            let id = res.or_else(|e| cx.throw_error(format!("{e}")))?;
            Ok(cx.string(id.to_string()))
        });
    };

    runtime.spawn(fut);

    Ok(promise)
}

fn bulk_create_jobs(mut cx: FunctionContext) -> JsResult<JsPromise> {
    let jobs = cx.argument::<JsString>(0)?;
    let jobs: Vec<JsJob> = from_json_string(&mut cx, jobs)?;

    let blobs = cx.argument::<JsValue>(1)?;
    let blob_lengths = cx.argument::<JsValue>(2)?;

    let blobs = blobs
        .downcast_or_throw::<JsUint8Array, _>(&mut cx)?
        .as_slice(&cx)
        .to_vec();

    let blob_lengths: Vec<usize> = blob_lengths
        .downcast_or_throw::<JsUint32Array, _>(&mut cx)?
        .as_slice(&cx)
        .iter()
        .map(|&v| v as usize)
        .collect();

    if jobs.len() != blob_lengths.len() {
        return cx.throw_error("jobs and blob_lengths must have the same length");
    }

    if blobs.len() != blob_lengths.iter().sum::<usize>() {
        return cx.throw_error("blob_lengths must sum to the length of blobs");
    }

    let mut blob_offset: usize = 0;
    let blobs: Vec<Option<Vec<u8>>> = blob_lengths
        .iter()
        .map(|&len| {
            if len == 0 {
                return None;
            }
            let blob = blobs[blob_offset..blob_offset + len].to_vec();
            blob_offset += len;
            Some(blob)
        })
        .collect();

    let jobs: Vec<JobInit> = jobs
        .into_iter()
        .zip(blobs)
        .map(|(job, blob)| job.to_job_init(blob))
        .collect();

    let (deferred, promise) = cx.promise();
    let channel = cx.channel();
    let runtime = runtime(&mut cx)?;

    let fut = async move {
        let manager = match MANAGER.get() {
            Some(manager) => manager,
            None => {
                deferred.settle_with(&channel, |mut cx| {
                    throw_null_err(&mut cx, "manager not initialized")
                });
                return;
            }
        };

        let res = manager.bulk_create_jobs(jobs).await;
        deferred.settle_with(&channel, move |mut cx| {
            let ids = res.or_else(|e| cx.throw_error(format!("{e}")))?;
            let returned = JsArray::new(&mut cx, ids.len());
            for (i, id) in ids.iter().enumerate() {
                let id = cx.string(id.to_string());
                returned.set(&mut cx, i as u32, id)?;
            }
            Ok(returned)
        });
    };

    runtime.spawn(fut);

    Ok(promise)
}

fn dequeue_jobs(mut cx: FunctionContext) -> JsResult<JsPromise> {
    let queue_name = cx.argument::<JsString>(0)?.value(&mut cx);

    let limit = cx.argument::<JsNumber>(1)?.value(&mut cx) as usize; // TODO - I don't love this cast

    let (deferred, promise) = cx.promise();
    let channel = cx.channel();
    let runtime = runtime(&mut cx)?;

    let fut = async move {
        let worker = match WORKER.get() {
            Some(worker) => worker,
            None => {
                deferred.settle_with(&channel, |mut cx| {
                    throw_null_err(&mut cx, "worker not initialized")
                });
                return;
            }
        };
        let jobs = worker.dequeue_jobs(&queue_name, limit).await;
        deferred.settle_with(&channel, move |mut cx| {
            let jobs = jobs.or_else(|e| cx.throw_error(format!("{e}")))?;
            let jobs = jobs_to_js_array(&mut cx, jobs)?;
            Ok(jobs)
        });
    };

    runtime.spawn(fut);

    Ok(promise)
}

fn dequeue_with_vm_state(mut cx: FunctionContext) -> JsResult<JsPromise> {
    let queue_name = cx.argument::<JsString>(0)?.value(&mut cx);

    let limit = cx.argument::<JsNumber>(1)?.value(&mut cx) as usize; // TODO - I don't love this cast

    let (deferred, promise) = cx.promise();
    let channel = cx.channel();
    let runtime = runtime(&mut cx)?;

    let fut = async move {
        let worker = match WORKER.get() {
            Some(worker) => worker,
            None => {
                deferred.settle_with(&channel, |mut cx| {
                    throw_null_err(&mut cx, "worker not initialized")
                });
                return;
            }
        };
        let jobs = worker.dequeue_with_vm_state(&queue_name, limit).await;
        deferred.settle_with(&channel, move |mut cx| {
            let jobs = jobs.or_else(|e| cx.throw_error(format!("{e}")))?;
            let jobs = jobs_to_js_array(&mut cx, jobs)?;
            Ok(jobs)
        });
    };

    runtime.spawn(fut);

    Ok(promise)
}

fn release_job(mut cx: FunctionContext) -> JsResult<JsPromise> {
    let arg1 = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg1
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {arg1}")))?;

    let (deferred, promise) = cx.promise();
    let channel = cx.channel();
    let runtime = runtime(&mut cx)?;

    let fut = async move {
        let worker = match WORKER.get() {
            Some(worker) => worker,
            None => {
                deferred.settle_with(&channel, |mut cx| {
                    throw_null_err(&mut cx, "worker not initialized")
                });
                return;
            }
        };
        // We await the handle here because this translates waiting on the join handle all the way to
        // a Js Promise.await.
        let res = worker.release_job(job_id, None).await;
        deferred.settle_with(&channel, move |mut cx| {
            res.or_else(|e| cx.throw_error(format!("{e}")))?;
            Ok(cx.null())
        });
    };

    runtime.spawn(fut);

    Ok(promise)
}

fn force_flush(mut cx: FunctionContext) -> JsResult<JsPromise> {
    let (deferred, promise) = cx.promise();
    let channel = cx.channel();
    let runtime = runtime(&mut cx)?;

    let fut = async move {
        let worker = match WORKER.get() {
            Some(worker) => worker,
            None => {
                deferred.settle_with(&channel, |mut cx| {
                    throw_null_err(&mut cx, "worker not initialized")
                });
                return;
            }
        };
        let res = worker.force_flush().await;
        deferred.settle_with(&channel, |mut cx| {
            res.or_else(|e| cx.throw_error(format!("{e}")))?;
            Ok(cx.null())
        });
    };

    runtime.spawn(fut);

    Ok(promise)
}

fn set_state(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {arg}")))?;

    let arg = cx.argument::<JsString>(1)?.value(&mut cx);
    let state: JobState = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job state: {arg}")))?;

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_state(job_id, state)
        .or_else(|e| cx.throw_error(format!("{e}")))?;

    Ok(cx.null())
}

fn set_queue(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {arg}")))?;

    let queue = cx.argument::<JsString>(1)?.value(&mut cx);

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_queue(job_id, &queue)
        .or_else(|e| cx.throw_error(format!("{e}")))?;

    Ok(cx.null())
}

fn set_priority(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {arg}")))?;

    let arg = cx.argument::<JsNumber>(1)?.value(&mut cx);
    let priority = arg as i16; // TODO - I /really/ don't love this cast

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_priority(job_id, priority)
        .or_else(|e| cx.throw_error(format!("{e}")))?;

    Ok(cx.null())
}

fn set_scheduled_at(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {arg}")))?;

    let arg = cx.argument::<JsString>(1)?.value(&mut cx);
    let scheduled: DateTime<Utc> = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid scheduled at: {arg}")))?;

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_scheduled_at(job_id, scheduled)
        .or_else(|e| cx.throw_error(format!("{e}")))?;

    Ok(cx.null())
}

fn set_vm_state(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {arg}")))?;

    // Tricky - we have to support passing nulls here, because that's how you clear vm state.
    let vm_state = cx.argument::<JsValue>(1)?;
    let vm_state =
        if vm_state.is_a::<JsNull, _>(&mut cx) || vm_state.is_a::<JsUndefined, _>(&mut cx) {
            None
        } else {
            Some(
                vm_state
                    .downcast_or_throw::<JsString, _>(&mut cx)?
                    .value(&mut cx)
                    .into_bytes(),
            )
        };

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_vm_state(job_id, vm_state)
        .or_else(|e| cx.throw_error(format!("{e}")))?;

    Ok(cx.null())
}

fn set_metadata(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {arg}")))?;

    // Tricky - we have to support passing nulls here, because that's how you clear metadata.
    let metadata = cx.argument::<JsValue>(1)?;
    let metadata =
        if metadata.is_a::<JsNull, _>(&mut cx) || metadata.is_a::<JsUndefined, _>(&mut cx) {
            None
        } else {
            Some(
                metadata
                    .downcast_or_throw::<JsString, _>(&mut cx)?
                    .value(&mut cx)
                    .into_bytes(),
            )
        };

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_metadata(job_id, metadata)
        .or_else(|e| cx.throw_error(format!("{e}")))?;

    Ok(cx.null())
}

fn set_parameters(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {arg}")))?;

    // Tricky - we have to support passing nulls here, because that's how you clear parameters.
    let parameters = cx.argument::<JsValue>(1)?;
    let parameters =
        if parameters.is_a::<JsNull, _>(&mut cx) || parameters.is_a::<JsUndefined, _>(&mut cx) {
            None
        } else {
            Some(
                parameters
                    .downcast_or_throw::<JsString, _>(&mut cx)?
                    .value(&mut cx)
                    .into_bytes(),
            )
        };

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_parameters(job_id, parameters)
        .or_else(|e| cx.throw_error(format!("{e}")))?;

    Ok(cx.null())
}

fn set_blob(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {arg}")))?;

    // Tricky - we have to support passing nulls here, because that's how you clear the blob.
    let blob = cx.argument::<JsValue>(1)?;
    let blob: Option<Vec<u8>> =
        if blob.is_a::<JsNull, _>(&mut cx) || blob.is_a::<JsUndefined, _>(&mut cx) {
            None
        } else {
            Some(
                blob.downcast_or_throw::<JsUint8Array, _>(&mut cx)?
                    .as_slice(&cx)
                    .to_vec(),
            )
        };

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_blob(job_id, blob)
        .or_else(|e| cx.throw_error(format!("{e}")))?;

    Ok(cx.null())
}

fn jobs_to_js_array<'a>(cx: &mut TaskContext<'a>, jobs: Vec<Job>) -> JsResult<'a, JsArray> {
    let js_array = JsArray::new(cx, jobs.len());

    for (i, job) in jobs.into_iter().enumerate() {
        let js_obj = JsObject::new(cx);
        let null = cx.null();

        let id_string = job.id.to_string();
        let js_id = cx.string(id_string);
        js_obj.set(cx, "id", js_id)?;

        let team_id = cx.number(job.team_id as f64);
        js_obj.set(cx, "teamId", team_id)?;

        if let Some(function_id) = job.function_id {
            let function_id_string = function_id.to_string();
            let js_function_id = cx.string(function_id_string);
            js_obj.set(cx, "functionId", js_function_id)?;
        } else {
            js_obj.set(cx, "functionId", null)?;
        }

        let js_created = cx
            .date(job.created.timestamp_millis() as f64)
            .expect("failed to create date");
        js_obj.set(cx, "created", js_created)?;

        if let Some(lock_id) = job.lock_id {
            let lock_id_string = lock_id.to_string();
            let js_lock_id = cx.string(lock_id_string);
            js_obj.set(cx, "lockId", js_lock_id)?;
        } else {
            js_obj.set(cx, "lockId", null)?;
        }

        if let Some(last_heartbeat) = job.last_heartbeat {
            let js_last_heartbeat = cx.string(last_heartbeat.to_rfc3339());
            js_obj.set(cx, "lastHeartbeat", js_last_heartbeat)?;
        } else {
            js_obj.set(cx, "lastHeartbeat", null)?;
        }

        let janitor_touch_count = cx.number(job.janitor_touch_count as f64);
        js_obj.set(cx, "janitorTouchCount", janitor_touch_count)?;
        let transition_count = cx.number(job.transition_count as f64);
        js_obj.set(cx, "transitionCount", transition_count)?;

        let js_last_transition = cx.string(job.last_transition.to_rfc3339());
        js_obj.set(cx, "lastTransition", js_last_transition)?;

        let js_queue_name = cx.string(&job.queue_name);
        js_obj.set(cx, "queueName", js_queue_name)?;

        let js_state = cx.string(format!("{:?}", job.state));
        js_obj.set(cx, "state", js_state)?;

        let priority = cx.number(job.priority as f64);
        js_obj.set(cx, "priority", priority)?;

        let js_scheduled = cx.string(job.scheduled.to_rfc3339());
        js_obj.set(cx, "scheduled", js_scheduled)?;

        if let Some(vm_state) = job.vm_state {
            let vm_state = match std::str::from_utf8(&vm_state) {
                Ok(v) => v,
                Err(e) => panic!("Invalid UTF-8 sequence in vm_state: {e}"),
            };
            let js_vm_state = cx.string(vm_state);
            js_obj.set(cx, "vmState", js_vm_state)?;
        } else {
            js_obj.set(cx, "vmState", null)?;
        }

        if let Some(metadata) = job.metadata {
            let metadata = match std::str::from_utf8(&metadata) {
                Ok(v) => v,
                Err(e) => panic!("Invalid UTF-8 sequence in metadata: {e}"),
            };
            let js_metadata = cx.string(metadata);
            js_obj.set(cx, "metadata", js_metadata)?;
        } else {
            js_obj.set(cx, "metadata", null)?;
        }

        if let Some(parameters) = job.parameters {
            let parameters = match std::str::from_utf8(&parameters) {
                Ok(v) => v,
                Err(e) => panic!("Invalid UTF-8 sequence in parameters: {e}"),
            };
            let js_parameters = cx.string(parameters);
            js_obj.set(cx, "parameters", js_parameters)?;
        } else {
            js_obj.set(cx, "parameters", null)?;
        }

        if let Some(blob) = job.blob {
            let mut js_blob = JsArrayBuffer::new(cx, blob.len())?;
            let js_blob_slice = js_blob.as_mut_slice(cx);
            js_blob_slice.copy_from_slice(&blob);
            js_obj.set(cx, "blob", js_blob)?;
        } else {
            js_obj.set(cx, "blob", null)?;
        }

        js_array.set(cx, i as u32, js_obj)?;
    }

    Ok(js_array)
}

impl JsJob {
    fn to_job_init(&self, blob: Option<Vec<u8>>) -> JobInit {
        JobInit {
            id: self.id,
            team_id: self.team_id,
            queue_name: self.queue_name.clone(),
            priority: self.priority,
            scheduled: self.scheduled,
            function_id: self.function_id,
            vm_state: self.vm_state.as_ref().map(|s| s.as_bytes().to_vec()),
            parameters: self.parameters.as_ref().map(|s| s.as_bytes().to_vec()),
            metadata: self.metadata.as_ref().map(|s| s.as_bytes().to_vec()),
            blob,
        }
    }
}

#[neon::main]
fn main(mut cx: ModuleContext) -> NeonResult<()> {
    cx.export_function("hello", hello)?;
    cx.export_function("initWorker", init_worker)?;
    cx.export_function("initManager", init_manager)?;
    cx.export_function("maybeInitWorker", maybe_init_worker)?;
    cx.export_function("maybeInitManager", maybe_init_manager)?;
    cx.export_function("createJob", create_job)?;
    cx.export_function("bulkCreateJobs", bulk_create_jobs)?;
    cx.export_function("dequeueJobs", dequeue_jobs)?;
    cx.export_function("dequeueJobsWithVmState", dequeue_with_vm_state)?;
    cx.export_function("releaseJob", release_job)?;
    cx.export_function("forceFlush", force_flush)?;
    cx.export_function("setState", set_state)?;
    cx.export_function("setQueue", set_queue)?;
    cx.export_function("setPriority", set_priority)?;
    cx.export_function("setScheduledAt", set_scheduled_at)?;
    cx.export_function("setVmState", set_vm_state)?;
    cx.export_function("setMetadata", set_metadata)?;
    cx.export_function("setParameters", set_parameters)?;
    cx.export_function("setBlob", set_blob)?;

    Ok(())
}
