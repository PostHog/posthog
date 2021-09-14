import { PluginEvent, PluginMeta, RetryError } from '@posthog/plugin-scaffold'

import {
    Hub,
    MetricMathOperations,
    PluginConfig,
    PluginConfigVMInternalResponse,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginTaskType,
} from '../../../../types'
import { addPublicJobIfNotExists } from '../../utils'
import {
    ExportEventsFromTheBeginningUpgrade,
    ExportEventsJobPayload,
    fetchEventsForInterval,
    fetchTimestampBoundariesForTeam,
} from './utils'

const EVENTS_TIME_INTERVAL = 10 * 60 * 1000 // 10 minutes
const EVENTS_PER_RUN = 100
const TIMESTAMP_CURSOR_KEY = 'timestamp_cursor1'
const MAX_TIMESTAMP_KEY = 'max_timestamp'
const EXPORT_RUNNING_KEY = 'is_export_running'

const INTERFACE_JOB_NAME = 'Export events from the beginning'

export function addHistoricalEventsExportCapability(
    hub: Hub,
    pluginConfig: PluginConfig,
    response: PluginConfigVMInternalResponse<PluginMeta<ExportEventsFromTheBeginningUpgrade>>
): void {
    const { methods, tasks, meta } = response

    // we can void this as the job appearing on the interface is not time-sensitive
    void addPublicJobIfNotExists(hub.db, pluginConfig.plugin_id, INTERFACE_JOB_NAME, {})

    const oldSetupPlugin = methods.setupPlugin

    methods.setupPlugin = async () => {
        // Fetch the max and min timestamps for a team's events
        const timestampBoundaries = await fetchTimestampBoundariesForTeam(hub.db, pluginConfig.team_id)

        // Set the max limit if we haven't already.
        // We don't update this because the export plugin would have already
        // started exporting *new* events so we should only export *historical* ones.
        const storedTimestampLimit = await meta.storage.get(MAX_TIMESTAMP_KEY, null)
        if (storedTimestampLimit) {
            meta.global.timestampLimit = new Date(String(storedTimestampLimit))
        } else {
            await meta.storage.set(MAX_TIMESTAMP_KEY, timestampBoundaries.max.toISOString())
            meta.global.timestampLimit = timestampBoundaries.max
        }

        // Set the lower timestamp boundary to start from.
        // We set it to an interval lower than the start point so the
        // first postgresIncrement call works correctly.
        const startCursor = timestampBoundaries.min.getTime() - EVENTS_TIME_INTERVAL
        await meta.utils.cursor.init(TIMESTAMP_CURSOR_KEY, startCursor)

        meta.global.minTimestamp = timestampBoundaries.min.getTime()

        await oldSetupPlugin?.()
    }

    meta.global.exportEventsFromTheBeginning = async (
        payload: ExportEventsJobPayload,
        meta: PluginMeta<ExportEventsFromTheBeginningUpgrade>
    ) => {
        if (payload.retriesPerformedSoFar >= 15) {
            // create some log error here
            return
        }

        let timestampCursor = payload.timestampCursor
        let intraIntervalOffset = payload.intraIntervalOffset ?? 0

        // This is the first run OR we're done with an interval
        if (payload.incrementTimestampCursor) {
            // Done with a timestamp interval, reset offset
            intraIntervalOffset = 0

            // This ensures we never process an interval twice
            const incrementedCursor = await meta.utils.cursor.increment(TIMESTAMP_CURSOR_KEY, EVENTS_TIME_INTERVAL)

            const progress = Math.round(
                ((incrementedCursor - meta.global.minTimestamp) /
                    (meta.global.timestampLimit.getTime() - meta.global.minTimestamp)) *
                    20
            )
            const progressBarCompleted = Array.from({ length: progress })
                .map((_) => '■')
                .join('')
            const progressBarRemaining = Array.from({ length: 20 - progress })
                .map((_) => '□')
                .join('')
            createLog(`Export progress: ${progressBarCompleted}${progressBarRemaining}`)
            timestampCursor = Number(incrementedCursor)
        }

        if (timestampCursor > meta.global.timestampLimit.getTime()) {
            await meta.storage.del(EXPORT_RUNNING_KEY)
            createLog(`Done exporting all events`)
            return
        }

        let events: PluginEvent[] = []

        let fetchEventsError: Error | unknown | null = null
        try {
            events = await fetchEventsForInterval(
                hub.db,
                pluginConfig.team_id,
                new Date(timestampCursor),
                intraIntervalOffset,
                EVENTS_TIME_INTERVAL,
                EVENTS_PER_RUN
            )
        } catch (error) {
            fetchEventsError = error
        }

        let exportEventsError: Error | unknown | null = null

        if (!fetchEventsError) {
            try {
                await methods.exportEvents!(events)
            } catch (error) {
                exportEventsError = error
            }
        }

        // Retry on every error from "our side" but only on a RetryError from the plugin dev
        if (fetchEventsError || exportEventsError instanceof RetryError) {
            const nextRetrySeconds = 2 ** payload.retriesPerformedSoFar * 3

            // "Failed processing events 0-100 from 2021-08-19T12:34:26.061Z to 2021-08-19T12:44:26.061Z. Retrying in 3s"
            createLog(
                `Failed processing events ${intraIntervalOffset}-${
                    intraIntervalOffset + EVENTS_PER_RUN
                } from ${new Date(timestampCursor).toISOString()} to ${new Date(
                    timestampCursor + EVENTS_TIME_INTERVAL
                ).toISOString()}. Retrying in ${nextRetrySeconds}s`
            )

            await meta.jobs
                .exportEventsFromTheBeginning({
                    intraIntervalOffset,
                    timestampCursor,
                    retriesPerformedSoFar: payload.retriesPerformedSoFar + 1,
                })
                .runIn(nextRetrySeconds, 'seconds')
        }

        createLog(
            `Successfully processed events ${intraIntervalOffset}-${
                intraIntervalOffset + EVENTS_PER_RUN
            } from ${new Date(timestampCursor).toISOString()} to ${new Date(
                timestampCursor + EVENTS_TIME_INTERVAL
            ).toISOString()}.`
        )

        const incrementTimestampCursor = events.length === 0

        incrementMetric('events_exported', events.length)

        await meta.jobs
            .exportEventsFromTheBeginning({
                timestampCursor,
                incrementTimestampCursor,
                retriesPerformedSoFar: 0,
                intraIntervalOffset: intraIntervalOffset + EVENTS_PER_RUN,
            })
            .runNow()
    }

    tasks.job['exportEventsFromTheBeginning'] = {
        name: 'exportEventsFromTheBeginning',
        type: PluginTaskType.Job,
        exec: (payload) => meta.global.exportEventsFromTheBeginning(payload as ExportEventsJobPayload, meta),
    }

    tasks.job[INTERFACE_JOB_NAME] = {
        name: INTERFACE_JOB_NAME,
        type: PluginTaskType.Job,
        // TODO: Accept timestamp as payload
        exec: async (_) => {
            const exportAlreadyRunning = await meta.storage.get(EXPORT_RUNNING_KEY, false)

            // only let one export run at a time
            if (exportAlreadyRunning) {
                return
            }

            await meta.storage.set(EXPORT_RUNNING_KEY, true)
            await meta.jobs
                .exportEventsFromTheBeginning({ retriesPerformedSoFar: 0, incrementTimestampCursor: true })
                .runNow()
        },
    }

    function incrementMetric(metricName: string, value: number) {
        hub.pluginMetricsManager.updateMetric({
            metricName,
            value,
            pluginConfig,
            metricOperation: MetricMathOperations.Increment,
        })
    }

    function createLog(message: string, type: PluginLogEntryType = PluginLogEntryType.Log) {
        void hub.db.queuePluginLogEntry({
            pluginConfig,
            message: `(${hub.instanceId}) ${message}`,
            source: PluginLogEntrySource.System,
            type: type,
            instanceId: hub.instanceId,
        })
    }
}
