import { Express } from 'ultimate-express'

export function registerStatus(app: Express): void {
    app.get('/status', (_req, res) => {
        res.json({
            service: 'agent-ingress',
            version: process.env.npm_package_version ?? 'dev',
            uptimeSeconds: Math.round(process.uptime()),
        })
    })
}
