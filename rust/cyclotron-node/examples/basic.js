const cyclotron = require('../.');
const crypto = require('crypto');

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

    console.log(cyclotron)

    // Most processes will only need to do one of these, but we can do both here for demonstration purposes
    await cyclotron.init_worker(JSON.stringify(poolConfig))
    await cyclotron.init_manager(JSON.stringify(managerConfig))

    // Maybe inits won't throw on re-calling, and are also short-circuiting to be almost free, so safe to call frequently
    // (although I still wouldn't call them in a loop)
    await cyclotron.maybe_init_worker(JSON.stringify(poolConfig))
    await cyclotron.maybe_init_manager(JSON.stringify(managerConfig))

    let now = new Date().toISOString()
    let queue_name = "default"
    let worker_type = "fetch"

    job_1 = {
        team_id: 1,
        waiting_on: worker_type,
        queue_name: queue_name,
        priority: 0,
        scheduled: now,
        function_id: crypto.randomUUID(), // Is nullable
        vm_state: null,
        parameters: null,
        metadata: null
    }

    job_2 = {
        team_id: 1,
        waiting_on: worker_type,
        queue_name: queue_name,
        priority: 0,
        scheduled: now,
        function_id: crypto.randomUUID(), // Is nullable
        vm_state: null,
        parameters: null,
        metadata: null
    }

    await cyclotron.create_job(JSON.stringify(job_1))
    await cyclotron.create_job(JSON.stringify(job_2))

    let jobs = await cyclotron.dequeue_jobs(queue_name, worker_type, 2)
    console.log(jobs)
}

main()