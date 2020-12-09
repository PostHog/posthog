const Sentry = require('@sentry/node')

const { isMainThread } = require('worker_threads')

if (isMainThread) {
    const Piscina = require('piscina')
    const { createConfig } = require('./config')
    module.exports = {
        makePiscina: (serverConfig) => {
            const piscina = new Piscina(createConfig(serverConfig, __filename))
            piscina.on('error', (error) => {
                Sentry.captureException(error)
                console.error('🔴 Piscina Worker Error!')
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
    module.exports = createWorker(workerData.serverConfig)
}

function areWeTestingWithJest() {
    return process.env.JEST_WORKER_ID !== undefined
}
