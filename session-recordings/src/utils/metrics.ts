/*
 * Provides a `meter` which can be used to gather metrics, and starts a server
 * on 3001 that exposes these metrics on /metrics in OpenMetrics format aka
 * Prometheus
 *
 * BEWARE: the OpenTelemetry API for OpenMetrics is pretty fluid atm, I had a
 * bit of trouble getting versions of the base lib and prometheus to work
 * together.
 */

import { PrometheusExporter, PrometheusSerializer } from '@opentelemetry/exporter-prometheus'
import { MeterProvider } from '@opentelemetry/sdk-metrics'
import { Router } from 'express'

export const meterProvider = new MeterProvider()
const exporter = new PrometheusExporter()
meterProvider.addMetricReader(exporter)

export const metricRoutes = Router()

metricRoutes.get('/_metrics', async (req, res) => {
    const results = await exporter.collect()
    res.setHeader('content-type', 'text/plain')
    return res.send(new PrometheusSerializer().serialize(results.resourceMetrics))
})

// Define the metrics we'll be exposing at /metrics
export const meter = meterProvider.getMeter('session-recordings-ingester')
export const counterMessagesReceived = meter.createCounter('messages_received')
export const counterS3FilesWritten = meter.createCounter('s3_files_written')
