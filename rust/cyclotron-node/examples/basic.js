const assert = require('assert')
const cyclotron = require('../.')
const crypto = require('crypto')

// Set of available job states
const JOB_STATES = Object.freeze({
    AVAILABLE: 'available',
    RUNNING: 'running',
    FAILED: 'failed',
    COMPLETED: 'completed',
})

const AVAILABLE_WORKERS = Object.freeze({
    FETCH: 'fetch',
    HOG: 'hog',
})

async function main() {
    let poolConfig = {
        db_url: 'postgresql://posthog:posthog@localhost:5432/cyclotron',
    }

    let managerConfig = {
        shards: [poolConfig],
    }

    // Most processes will only need to do one of these, but we can do both here for demonstration purposes
    await cyclotron.initWorker(JSON.stringify(poolConfig))
    await cyclotron.initManager(JSON.stringify(managerConfig))

    // Maybe inits won't throw on re-calling, and are also short-circuiting to be almost free, so safe to call frequently
    // (although I still wouldn't call them in a loop)
    await cyclotron.maybeInitWorker(JSON.stringify(poolConfig))
    await cyclotron.maybeInitManager(JSON.stringify(managerConfig))

    let five_mintes_ago = new Date(new Date().getTime() - 5 * 60000).toISOString()
    let queue_name = 'default'

    let job_1 = {
        team_id: 1,
        queue_name,
        priority: 0,
        scheduled: five_mintes_ago,
        function_id: crypto.randomUUID(), // Is nullable
        vm_state: null,
        parameters: null,
        blob: null,
        metadata: null,
    }

    let job_2 = {
        team_id: 1,
        queue_name,
        priority: 1,
        scheduled: five_mintes_ago,
        function_id: crypto.randomUUID(), // Is nullable
        vm_state: null,
        parameters: null,
        blob: null,
        metadata: null,
    }

    await cyclotron.createJob(JSON.stringify(job_1))
    await cyclotron.createJob(JSON.stringify(job_2))

    // Jobs (as well as any other 'complex' data shape) are serialized across the API boundary,
    // because that's (according to the neon maintainers) /actually faster/ than doing a bunch
    // of cross-runtime pointer chasing.
    let jobs = JSON.parse(await cyclotron.dequeueJobs(queue_name, 2))
    assert(jobs.length === 2)
    assert(jobs[0].function_id === job_1.function_id)
    assert(jobs[1].function_id === job_2.function_id)

    job_1 = jobs[0]
    job_2 = jobs[1]

    // All of these throw if the job hasn't been dequeued by the worker created when init_worker was called,
    // or if there's some serde error - generally, interacting with the cyclotron should involve try/catch in
    // some far outer catch. We can iterate on this API to make it more ergonomic with time, but
    // my js/ts is... rusty (co-pilot wrote this joke)
    cyclotron.setState(job_1.id, JOB_STATES.AVAILABLE)
    cyclotron.setState(job_2.id, JOB_STATES.AVAILABLE)

    cyclotron.setQueue(job_1.id, 'non-default')
    cyclotron.setQueue(job_2.id, 'non-default')

    // Priority is lowest-first, so this means we can assert that job_2 will be returned first on subsequent dequeue_jobs
    cyclotron.setPriority(job_1.id, 2)
    cyclotron.setPriority(job_2.id, 1)

    let ten_minutes_ago = new Date(new Date().getTime() - 10 * 60000).toISOString()
    cyclotron.setScheduledAt(job_1.id, ten_minutes_ago)
    cyclotron.setScheduledAt(job_2.id, ten_minutes_ago)

    cyclotron.setVmState(job_1.id, JSON.stringify({ state: 'running' }))
    cyclotron.setVmState(job_2.id, JSON.stringify({ state: 'running' }))

    cyclotron.setParameters(job_1.id, JSON.stringify({ parameters: 'running' }))
    cyclotron.setParameters(job_2.id, JSON.stringify({ parameters: 'running' }))

    cyclotron.setMetadata(job_1.id, JSON.stringify({ metadata: 'running' }))
    cyclotron.setMetadata(job_2.id, JSON.stringify({ metadata: 'running' }))

    // Flush the updates queued up above back to the queue. Subsequent calls to flush
    // will throw if a job isn't re-acquired. Flushes will fail if a job state update
    // isn't included (workers should not purposefully leave jobs in a running state)
    await cyclotron.flushJob(job_1.id)
    await cyclotron.flushJob(job_2.id)

    jobs = JSON.parse(await cyclotron.dequeueWithVmState('non-default', 2))

    assert(jobs[0].id == job_2.id)
    assert(jobs[1].id == job_1.id)

    assert(jobs[0].function_id === job_2.function_id)
    assert(jobs[1].function_id === job_1.function_id)

    assert(jobs[0].team_id === job_2.team_id)
    assert(jobs[1].team_id === job_1.team_id)

    assert(jobs[0].queue_name === 'non-default')
    assert(jobs[1].queue_name === 'non-default')

    assert(jobs[0].priority === 1)
    assert(jobs[1].priority === 2)

    assert(jobs[0].scheduled === ten_minutes_ago)
    assert(jobs[1].scheduled === ten_minutes_ago)

    assert(jobs[0].vm_state === JSON.stringify({ state: 'running' }))
    assert(jobs[1].vm_state === JSON.stringify({ state: 'running' }))
    assert(jobs[0].parameters === JSON.stringify({ parameters: 'running' }))
    assert(jobs[1].parameters === JSON.stringify({ parameters: 'running' }))
    assert(jobs[0].metadata === JSON.stringify({ metadata: 'running' }))
    assert(jobs[1].metadata === JSON.stringify({ metadata: 'running' }))

    // Now we'll mark these jobs as completed
    cyclotron.setState(job_1.id, JOB_STATES.COMPLETED)
    cyclotron.setState(job_2.id, JOB_STATES.COMPLETED)

    // And flush them back to the queue
    await cyclotron.flushJob(job_1.id)
    await cyclotron.flushJob(job_2.id)
}

main()
