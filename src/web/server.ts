import { fastify, FastifyRequest, FastifyReply } from 'fastify'

export const webServer = fastify()

async function getEvent(request: FastifyRequest, reply: FastifyReply): Promise<Record<string, any>> {
    return {}
}

webServer.get('*', getEvent)
webServer.post('*', getEvent)

export async function startWebServer(port: string | number, hostname?: string): Promise<void> {
    console.info(`👾 Starting web server…`)
    try {
        const address = await webServer.listen(port, hostname)
        console.info(`✅ Web server listening on ${address}!`)
    } catch (e) {
        console.error(`🛑 Web server could not start! ${e}`)
    }
}

export async function stopWebServer(): Promise<void> {
    await webServer.close()
    console.info(`\n🛑 Web server cleaned up!`)
}
