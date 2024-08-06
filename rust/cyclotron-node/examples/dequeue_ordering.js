const assert = require('assert');
const cyclotron = require('../.');
const crypto = require('crypto');


// This file (and the rust equivalent) are me trying to figure out why, sometimes, the order of jobs returned
// from the queue does not match the priority order set previous (BUT ONLY IN NODE). I've been unable to reproduce
// this in rust, so the error probably lies in some node binding gremlins, but I have /not even close/ to enough
// knowledge of the node runtime to figure out why that might be the case. I've checked, and the priority is being
// set correctly in the DB, it's just ??? not being used ??? for the subsequent dequeue call ??? sometimes ???.

// UPDATE - this file now also runs without issues... I don't know what's going on, but putting it down to
// "oliver needs to stop writing code at 1am"... Gonna go sketch out some management command stuff now.

const JOB_STATES = Object.freeze({
    AVAILABLE: "available",
    RUNNING: "running",
    FAILED: "failed",
    COMPLETED: "completed",
});

const AVAILABLE_WORKERS = Object.freeze({
    FETCH: "fetch",
    HOG: "hog",
});

async function main() {
    let poolConfig = {
        host: 'localhost',
        port: 5432,
        user: 'posthog',
        password: 'posthog',
        db: 'posthog'
    }

    let managerConfig = {
        shards: [poolConfig]
    }

    // Most processes will only need to do one of these, but we can do both here for demonstration purposes
    await cyclotron.init_worker(JSON.stringify(poolConfig))
    await cyclotron.init_manager(JSON.stringify(managerConfig))

    // Maybe inits won't throw on re-calling, and are also short-circuiting to be almost free, so safe to call frequently
    // (although I still wouldn't call them in a loop)
    await cyclotron.maybe_init_worker(JSON.stringify(poolConfig))
    await cyclotron.maybe_init_manager(JSON.stringify(managerConfig))

    let five_mintes_ago = new Date(new Date().getTime() - 5 * 60000).toISOString()
    let queue_name = "default"

    let job_1 = {
        team_id: 1,
        waiting_on: AVAILABLE_WORKERS.FETCH,
        queue_name: queue_name,
        priority: 0,
        scheduled: five_mintes_ago,
        function_id: crypto.randomUUID(), // Is nullable
        vm_state: null,
        parameters: null,
        metadata: null
    }

    let job_2 = {
        team_id: 1,
        waiting_on: AVAILABLE_WORKERS.FETCH,
        queue_name: queue_name,
        priority: 1,
        scheduled: five_mintes_ago,
        function_id: crypto.randomUUID(), // Is nullable
        vm_state: null,
        parameters: null,
        metadata: null
    }

    let start = new Date().getTime()
    let count = 0;
    while(true) {

        await cyclotron.create_job(JSON.stringify(job_1))
        await cyclotron.create_job(JSON.stringify(job_2))

        // Jobs (as well as any other 'complex' data shape) are serialized across the API boundary,
        // because that's (according to the neon maintainers) /actually faster/ than doing a bunch
        // of cross-runtime pointer chasing.
        let jobs = JSON.parse(await cyclotron.dequeue_jobs(queue_name, AVAILABLE_WORKERS.FETCH, 2))
        assert(jobs.length === 2)
        assert(jobs[0].function_id === job_1.function_id)
        assert(jobs[1].function_id === job_2.function_id)

        job_1 = jobs[0]
        job_2 = jobs[1]

        cyclotron.set_state(job_1.id, JOB_STATES.AVAILABLE)
        cyclotron.set_state(job_2.id, JOB_STATES.AVAILABLE)

        cyclotron.set_priority(job_1.id, 2)
        cyclotron.set_priority(job_2.id, 1)

        await cyclotron.flush_job(job_1.id)
        await cyclotron.flush_job(job_2.id)

        jobs = JSON.parse(await cyclotron.dequeue_with_vm_state("default", AVAILABLE_WORKERS.FETCH, 2))

        // Now, since we've re-ordered the jobs, we should expect job_2 to be returned first
        assert(jobs.length === 2)
        assert(jobs[0].id == job_2.id)
        assert(jobs[1].id == job_1.id)

        // Now we'll mark these jobs as completed
        cyclotron.set_state(job_1.id, JOB_STATES.COMPLETED)
        cyclotron.set_state(job_2.id, JOB_STATES.COMPLETED)

        // And flush them back to the queue
        await cyclotron.flush_job(job_1.id)
        await cyclotron.flush_job(job_2.id)

        count++;
        if (count % 10 == 0) {
            let elapsed = new Date().getTime() - start
            console.log(`Looped ${count} jobs in ${elapsed}ms)`)
        }
        if(count > 2000) {
            break;
        }
    }

}

main()