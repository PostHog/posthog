const Sentry = require('@sentry/node')
const { isMainThread, threadId } = require('worker_threads')

function areWeTestingWithJest() {
    return Boolean(process.env.JEST_WORKER_ID)
}

if (isMainThread) {
    const Piscina = require('piscina')
    const { createConfig } = require('./config')
    module.exports = {
        makePiscina: (serverConfig) => {
            const piscina = new Piscina(createConfig(serverConfig, __filename))
            piscina.on('error', (error) => {
                Sentry.captureException(error)
                console.error(`⚠️ Piscina worker thread ${threadId} error!`)
                console.error(error)
            })
            return piscina
        },
    }
} else {
    if (areWeTestingWithJest()) {
        require('ts-node').register()
    }

    const { createWorker } = require('./worker')
    const { workerData } = require('piscina')
    module.exports = createWorker(workerData.serverConfig, threadId)
}
