import { cloneObject, setLogLevel } from '../utils'
import { runPlugins, setupPlugins } from '../plugins'
import { createServer } from '../server'
import { PluginsServerConfig } from '../types'

type TaskWorker = ({ task, args }: { task: string; args: any }) => Promise<any>

export async function createWorker(config: PluginsServerConfig): Promise<TaskWorker> {
    setLogLevel(config.LOG_LEVEL)

    console.info('🧵 Starting Piscina Worker Thread')

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
    }
}
