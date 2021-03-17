const Sentry = require('@sentry/node')
const { isMainThread, threadId } = require('worker_threads')

if (isMainThread) {
    const Piscina = require('@posthog/piscina')
    const { createConfig } = require('./config')
    module.exports = {
        makePiscina: (serverConfig) => {
            const piscina = new Piscina(createConfig(serverConfig, __filename))
            piscina.on('error', (error) => {
                Sentry.captureException(error)
                console.error('⚠️', 'Piscina worker thread error:\n', error)
            })
            return piscina
        },
    }
} else {
    if (process.env.NODE_ENV === 'test') {
        require('ts-node').register()
    }

    const { createWorker } = require('./worker')
    const { workerData } = require('@posthog/piscina')
    module.exports = createWorker(workerData.serverConfig, threadId)
}
