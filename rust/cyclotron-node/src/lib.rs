use chrono::{DateTime, Utc};

use cyclotron_core::{JobInit, JobState, ManagerConfig, PoolConfig, QueueManager, Worker};
use neon::{
    handle::Handle,
    prelude::{Context, FunctionContext, ModuleContext},
    result::{JsResult, NeonResult},
    types::{JsNull, JsNumber, JsPromise, JsString, JsValue},
};
use once_cell::sync::OnceCell;
use serde::de::DeserializeOwned;
use serde_json::Value;
use tokio::runtime::Runtime;
use uuid::Uuid;

static WORKER: OnceCell<Worker> = OnceCell::new();
static MANAGER: OnceCell<QueueManager> = OnceCell::new();
static RUNTIME: OnceCell<Runtime> = OnceCell::new();

fn runtime<'a, C: Context<'a>>(cx: &mut C) -> NeonResult<&'static Runtime> {
    RUNTIME
        .get_or_try_init(Runtime::new)
        .or_else(|e| cx.throw_error(format!("failed to create tokio runtime: {}", e)))
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
        serde_json::from_str(&object.value(cx)).or_else(|e| cx.throw_error(format!("{}", e)))?;
    Ok(value)
}

pub fn to_json_string<'a, T, C>(cx: &mut C, value: T) -> NeonResult<String>
where
    T: serde::Serialize,
    C: Context<'a>,
{
    let value = serde_json::to_string(&value)
        .or_else(|e| cx.throw_error(format!("failed to serialize value: {}", e)))?;
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

    let (deferred, promise) = cx.promise();
    let channel = cx.channel();
    let runtime = runtime(&mut cx)?;

    let fut = async move {
        let worker = Worker::new(config).await;
        deferred.settle_with(&channel, move |mut cx| {
            if WORKER.get().is_some() && !throw_on_reinit {
                return Ok(cx.null()); // Short circuit to make using maybe_init a no-op
            }
            let worker = worker.or_else(|e| cx.throw_error(format!("{}", e)))?;
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
            let manager = manager.or_else(|e| cx.throw_error(format!("{}", e)))?;
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

fn create_job(mut cx: FunctionContext) -> JsResult<JsPromise> {
    let arg1: Handle<JsString> = cx.argument::<JsString>(0)?;
    let job: JobInit = from_json_string(&mut cx, arg1)?;

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
        let job = manager.create_job(job).await;
        deferred.settle_with(&channel, move |mut cx| {
            job.or_else(|e| cx.throw_error(format!("{}", e)))?;
            Ok(cx.null())
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
            let jobs = jobs.or_else(|e| cx.throw_error(format!("{}", e)))?;
            let jobs = to_json_string(&mut cx, jobs)?;
            Ok(cx.string(jobs))
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
            let jobs = jobs.or_else(|e| cx.throw_error(format!("{}", e)))?;
            let jobs = to_json_string(&mut cx, jobs)?;
            Ok(cx.string(jobs))
        });
    };

    runtime.spawn(fut);

    Ok(promise)
}

fn flush_job(mut cx: FunctionContext) -> JsResult<JsPromise> {
    let arg1 = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg1
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {}", arg1)))?;

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
        let res = worker.flush_job(job_id).await;
        deferred.settle_with(&channel, move |mut cx| {
            res.or_else(|e: cyclotron_core::QueueError| cx.throw_error(format!("{}", e)))?;
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
        .or_else(|_| cx.throw_error(format!("invalid job id: {}", arg)))?;

    let arg = cx.argument::<JsString>(1)?.value(&mut cx);
    let state: JobState = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job state: {}", arg)))?;

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_state(job_id, state)
        .or_else(|e| cx.throw_error(format!("{}", e)))?;

    Ok(cx.null())
}

fn set_queue(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {}", arg)))?;

    let queue = cx.argument::<JsString>(1)?.value(&mut cx);

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_queue(job_id, &queue)
        .or_else(|e| cx.throw_error(format!("{}", e)))?;

    Ok(cx.null())
}

fn set_priority(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {}", arg)))?;

    let arg = cx.argument::<JsNumber>(1)?.value(&mut cx);
    let priority = arg as i16; // TODO - I /really/ don't love this cast

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_priority(job_id, priority)
        .or_else(|e| cx.throw_error(format!("{}", e)))?;

    Ok(cx.null())
}

fn set_scheduled_at(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {}", arg)))?;

    let arg = cx.argument::<JsString>(1)?.value(&mut cx);
    let scheduled: DateTime<Utc> = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid scheduled at: {}", arg)))?;

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_scheduled_at(job_id, scheduled)
        .or_else(|e| cx.throw_error(format!("{}", e)))?;

    Ok(cx.null())
}

fn set_vm_state(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {}", arg)))?;

    // Tricky - we have to support passing nulls here, because that's how you clear vm state.
    let vm_state = cx.argument::<JsValue>(1)?;
    let vm_state = if vm_state.is_a::<JsNull, _>(&mut cx) {
        None
    } else {
        Some(
            vm_state
                .downcast_or_throw::<JsString, _>(&mut cx)?
                .value(&mut cx),
        )
    };

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_vm_state(job_id, vm_state)
        .or_else(|e| cx.throw_error(format!("{}", e)))?;

    Ok(cx.null())
}

fn set_metadata(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {}", arg)))?;

    // Tricky - we have to support passing nulls here, because that's how you clear metadata.
    let metadata = cx.argument::<JsValue>(1)?;
    let metadata = if metadata.is_a::<JsNull, _>(&mut cx) {
        None
    } else {
        Some(
            metadata
                .downcast_or_throw::<JsString, _>(&mut cx)?
                .value(&mut cx),
        )
    };

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_metadata(job_id, metadata)
        .or_else(|e| cx.throw_error(format!("{}", e)))?;

    Ok(cx.null())
}

fn set_parameters(mut cx: FunctionContext) -> JsResult<JsNull> {
    let arg = cx.argument::<JsString>(0)?.value(&mut cx);
    let job_id: Uuid = arg
        .parse()
        .or_else(|_| cx.throw_error(format!("invalid job id: {}", arg)))?;

    // Tricky - we have to support passing nulls here, because that's how you clear parameters.
    let parameters = cx.argument::<JsValue>(1)?;
    let parameters = if parameters.is_a::<JsNull, _>(&mut cx) {
        None
    } else {
        Some(
            parameters
                .downcast_or_throw::<JsString, _>(&mut cx)?
                .value(&mut cx),
        )
    };

    WORKER
        .get()
        .map_or_else(|| cx.throw_error("worker not initialized"), Ok)?
        .set_parameters(job_id, parameters)
        .or_else(|e| cx.throw_error(format!("{}", e)))?;

    Ok(cx.null())
}

#[neon::main]
fn main(mut cx: ModuleContext) -> NeonResult<()> {
    cx.export_function("hello", hello)?;
    cx.export_function("initWorker", init_worker)?;
    cx.export_function("initManager", init_manager)?;
    cx.export_function("maybeInitWorker", maybe_init_worker)?;
    cx.export_function("maybeInitManager", maybe_init_manager)?;
    cx.export_function("createJob", create_job)?;
    cx.export_function("dequeueJobs", dequeue_jobs)?;
    cx.export_function("dequeueJobsWithVmState", dequeue_with_vm_state)?;
    cx.export_function("flushJob", flush_job)?;
    cx.export_function("setState", set_state)?;
    cx.export_function("setQueue", set_queue)?;
    cx.export_function("setPriority", set_priority)?;
    cx.export_function("setScheduledAt", set_scheduled_at)?;
    cx.export_function("setVmState", set_vm_state)?;
    cx.export_function("setMetadata", set_metadata)?;
    cx.export_function("setParameters", set_parameters)?;

    Ok(())
}
