import { fastify, FastifyInstance } from 'fastify'
import { PluginsServer } from 'types'

export function buildFastifyInstance(): FastifyInstance {
    const fastifyInstance = fastify()
    return fastifyInstance
}

export async function stopFastifyInstance(fastifyInstance: FastifyInstance): Promise<void> {
    await fastifyInstance.close()
    console.info(`🛑 Web server closed!`)
}

export async function startFastifyInstance(pluginsServer: PluginsServer): Promise<FastifyInstance> {
    console.info(`👾 Starting web server…`)
    const fastifyInstance = buildFastifyInstance()
    try {
        const address = await fastifyInstance.listen(pluginsServer.WEB_PORT, pluginsServer.WEB_HOSTNAME)
        console.info(`✅ Web server listening on ${address}!`)
    } catch (e) {
        console.error(`🛑 Web server could not start! ${e}`)
        return fastifyInstance
    }
    return fastifyInstance
}
