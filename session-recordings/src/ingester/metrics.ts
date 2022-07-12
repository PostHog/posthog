/*
 * Provides a `meter` which can be used to gather metrics, and starts a server
 * on 3001 that exposes these metrics on /metrics in OpenMetrics format aka
 * Prometheus
 *
 * BEWARE: the OpenTelemetry API for OpenMetrics is pretty fluid atm, I had a
 * bit of trouble getting versions of the base lib and prometheus to work
 * together.
 */

import { PrometheusExporter } from '@opentelemetry/exporter-prometheus'
import { MeterProvider } from '@opentelemetry/sdk-metrics-base'

const exporter = new PrometheusExporter({ port: 3001, host: '0.0.0.0', preventServerStart: false })
export const meterProvider = new MeterProvider()

meterProvider.addMetricReader(exporter)

// Make sure we kill the exporter on shutdown
const signalTraps = ['SIGTERM', 'SIGINT', 'SIGUSR2']

signalTraps.map((type) => {
    process.once(type, async () => {
        try {
            await exporter.stopServer()
        } finally {
            process.kill(process.pid, type)
        }
    })
})
