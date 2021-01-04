import { fastify, FastifyInstance } from 'fastify'
import { PluginsServer } from 'types'
import { status } from '../status'

export function buildFastifyInstance(): FastifyInstance {
    const fastifyInstance = fastify()
    return fastifyInstance
}

export async function stopFastifyInstance(fastifyInstance: FastifyInstance): Promise<void> {
    await fastifyInstance.close()
    status.info('🛑', 'Web server closed!')
}

export async function startFastifyInstance(pluginsServer: PluginsServer): Promise<FastifyInstance> {
    status.info('👾', 'Starting web server…')
    const fastifyInstance = buildFastifyInstance()
    try {
        const address = await fastifyInstance.listen(pluginsServer.WEB_PORT, pluginsServer.WEB_HOSTNAME)
        status.info('✅', `Web server listening on ${address}!`)
    } catch (e) {
        status.error('🛑', `Web server could not start! ${e}`)
        return fastifyInstance
    }
    return fastifyInstance
}
