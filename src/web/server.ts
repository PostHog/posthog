import { fastify, FastifyInstance } from 'fastify'

export function buildFastifyInstance(): FastifyInstance {
    const fastifyInstance = fastify()
    return fastifyInstance
}

export async function stopFastifyInstance(fastifyInstance: FastifyInstance): Promise<void> {
    await fastifyInstance.close()
    console.info(`\n🛑 Web server cleaned up!`)
}

export async function startFastifyInstance(
    port: string | number = 3008,
    hostname?: string,
    withSignalHandling = true
): Promise<FastifyInstance> {
    console.info(`👾 Starting web server…`)
    const fastifyInstance = buildFastifyInstance()
    try {
        const address = await fastifyInstance.listen(port, hostname)
        console.info(`✅ Web server listening on ${address}!`)
    } catch (e) {
        console.error(`🛑 Web server could not start! ${e}`)
        return fastifyInstance
    }
    return fastifyInstance
}
