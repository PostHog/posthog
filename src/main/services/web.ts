import { fastify, FastifyInstance } from 'fastify'
import { Hub } from 'types'

import { status } from '../../utils/status'

export function buildFastifyInstance(): FastifyInstance {
    const fastifyInstance = fastify()
    return fastifyInstance
}

export async function stopFastifyInstance(fastifyInstance: FastifyInstance): Promise<void> {
    await fastifyInstance.close()
    status.info('🛑', 'Web server closed!')
}

export async function startFastifyInstance(pluginsServer: Hub): Promise<FastifyInstance> {
    status.info('👾', 'Starting web server…')
    const fastifyInstance = buildFastifyInstance()
    try {
        const address = await fastifyInstance.listen({ port: pluginsServer.WEB_PORT, host: pluginsServer.WEB_HOSTNAME })
        status.info('✅', `Web server listening on ${address}!`)
    } catch (error) {
        status.error('🛑', 'Web server could not start:\n', error)
        return fastifyInstance
    }
    return fastifyInstance
}
