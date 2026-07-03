// Sidecar entrypoint: load config, start the server, drain on SIGTERM. Kept separate from server.ts so the
// test can import startServer without booting a real listener (`tsx src/main.ts` is the only thing that runs this).
import { loadConfig } from './config.ts'
import { startServer } from './server.ts'

const cfg = loadConfig()
const server = startServer(cfg.port, cfg.maxConcurrency, cfg.maxBodyBytes)

for (const sig of ['SIGINT', 'SIGTERM'] as const) {
    process.on(sig, () => {
        // Force-exit backstop so we never hang past the pod's termination grace period.
        const force = setTimeout(() => process.exit(1), 10_000)
        force.unref()
        server.close(() => {
            clearTimeout(force)
            process.exit(0)
        })
        // Drop the consumer's idle keep-alive sockets so close() can complete; in-flight scrubs still drain.
        server.closeIdleConnections()
    })
}
