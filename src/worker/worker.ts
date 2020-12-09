import { runPlugins, runPluginsOnBatch, setupPlugins } from '../plugins'
import { cloneObject } from '../utils'
import { createServer } from '../server'
import { PluginsServerConfig } from '../types'
import { initApp } from '../init'

type TaskWorker = ({ task, args }: { task: string; args: any }) => Promise<any>

export async function createWorker(config: PluginsServerConfig): Promise<TaskWorker> {
    console.info('🧵 Starting Piscina Worker Thread')

    initApp(config)

    const [server, closeServer] = await createServer(config)
    await setupPlugins(server)

    const closeJobs = async () => {
        await closeServer()
    }
    for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
        process.on(signal, closeJobs)
    }

    return async ({ task, args }) => {
        if (task === 'hello') {
            return `hello ${args[0]}!`
        }
        if (task === 'processEvent') {
            const processedEvent = await runPlugins(server, args.event)
            // must clone the object, as we may get from VM2 something like { ..., properties: Proxy {} }
            return cloneObject(processedEvent as Record<string, any>)
        }
        if (task === 'processEventBatch') {
            const processedEvents = await runPluginsOnBatch(server, args.batch)
            // must clone the object, as we may get from VM2 something like { ..., properties: Proxy {} }
            return cloneObject(processedEvents as any[])
        }
    }
}
