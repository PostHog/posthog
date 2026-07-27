import { loadConfig } from './config'
import { createBot } from './recall'
import { startServer } from './server'

const config = loadConfig()
startServer(config)

console.info(`meeting-bot listening on :${config.port}`)
console.info(`stage page      ${config.publicBaseUrl}/stage?token=${config.sharedSecret}`)
console.info(`transcript ws   ${config.publicBaseUrl.replace(/^http/, 'ws')}/recall/transcript`)
console.info(`trigger phrase  "${config.triggerPhrase}"`)

if (!process.env.SHARED_SECRET) {
    console.warn(`SHARED_SECRET was not set, so this run generated ${config.sharedSecret}.`)
    console.warn('Bots dispatched by a previous run point at the old secret and will be rejected.')
}

const meetingUrl = process.env.MEETING_URL
if (meetingUrl) {
    createBot(config, meetingUrl).then(
        (bot) => console.info(`bot ${bot.id} joining ${meetingUrl}`),
        (error) => console.error('failed to dispatch bot:', error)
    )
}
