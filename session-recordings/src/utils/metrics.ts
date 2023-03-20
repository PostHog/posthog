/*
 * Provides a `meter` which can be used to gather metrics, and starts a server
 * on 3001 that exposes these metrics on /metrics in OpenMetrics format aka
 * Prometheus
 *
 * BEWARE: the OpenTelemetry API for OpenMetrics is pretty fluid atm, I had a
 * bit of trouble getting versions of the base lib and prometheus to work
 * together.
 */

import { PrometheusSerializer } from '@opentelemetry/exporter-prometheus'
import { AggregationTemporality, MeterProvider, MetricReader } from '@opentelemetry/sdk-metrics-base'
import { Router } from 'express'

export const meterProvider = new MeterProvider()

class Exporter extends MetricReader {
    selectAggregationTemporality() {
        return AggregationTemporality.CUMULATIVE
    }

    protected onForceFlush(): Promise<void> {
        return
    }

    protected onShutdown(): Promise<void> {
        return
    }
}

const exporter = new Exporter()

meterProvider.addMetricReader(exporter)

export const metricRoutes = Router()

metricRoutes.get('/_metrics', async (req, res) => {
    const results = await exporter.collect()
    res.setHeader('content-type', 'text/plain')
    return res.send(new PrometheusSerializer().serialize(results.resourceMetrics))
})
