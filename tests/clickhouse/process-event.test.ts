import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../src/shared/ingestion/topics'
import { Event, PluginsServerConfig } from '../../src/types'
import { resetTestDatabaseClickhouse } from '../helpers/clickhouse'
import { resetKafka } from '../helpers/kafka'
import { createProcessEventTests } from '../shared/process-event'

jest.setTimeout(180_000) // 3 minute timeout

const extraServerConfig: Partial<PluginsServerConfig> = {
    KAFKA_ENABLED: true,
    KAFKA_HOSTS: process.env.KAFKA_HOSTS || 'kafka:9092',
    KAFKA_CONSUMPTION_TOPIC: KAFKA_EVENTS_PLUGIN_INGESTION,
}

describe('process event (clickhouse)', () => {
    beforeAll(async () => {
        await resetKafka(extraServerConfig)
    })

    beforeEach(async () => {
        await resetTestDatabaseClickhouse(extraServerConfig)
    })

    createProcessEventTests('clickhouse', extraServerConfig)
})
