import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs, inStorybookTestRunner, sampleOne, uuid } from 'lib/utils'
import { deterministicRandom } from 'lib/utils/random'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { MockSignature } from '~/mocks/utils'
import { LogMessage, LogSeverityLevel } from '~/queries/schema/schema-general'

const delayIfNotTestRunner = async (): Promise<void> => {
    await new Promise((resolve) => setTimeout(resolve, inStorybookTestRunner() ? 0 : 200 + Math.random() * 1000))
}

const keysAndValues: Record<string, string[]> = {
    'service.name': [
        'posthog-web',
        'posthog-feature-flags',
        'posthog-surveys',
        'posthog-web-django',
        'cdp-behavioural-events-consumer',
        'cdp-events-consumer',
        'cdp-legacy-events-consumer',
        'capture',
    ],
    'k8s.namespace.name': ['posthog', 'internal', 'billing'],
    'k8s.pod.name': [
        'posthog-web',
        'posthog-feature-flags',
        'posthog-surveys',
        'posthog-web-django',
        'cdp-behavioural-events-consumer',
        'cdp-events-consumer',
        'cdp-legacy-events-consumer',
        'capture',
    ],
    'k8s.container.restart_count': ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
    'k8s.node.name': [
        'node-1',
        'node-2',
        'node-3',
        'node-4',
        'node-5',
        'node-6',
        'node-7',
        'node-8',
        'node-9',
        'node-10',
    ],
    'log.iostream': ['stdout', 'stderr'],
}

const EXAMPLES: Record<
    string,
    {
        attributes: Record<string, string>
        logs: { message: string; level: LogSeverityLevel; attributes?: Record<string, string> }[]
    }
> = {
    'posthog-web': {
        attributes: {
            'k8s.namespace.name': 'posthog',
            'service.name': 'posthog-web',
            'k8s.pod.name': 'posthog-web',
            'k8s.container.name': 'posthog-web',
        },
        logs: [
            {
                message:
                    '{"request_id": "0904e6ff-da7e-4d66-af79-0c111bb47cab", "ip": "1.0.0.1", "event": "geoIP computation error: The address 172.0.1.1 is not in the database.",  "host": "us.i.posthog.com", "container_hostname": "posthog-web-django-c5f54bd98-cswsg", "timestamp": "2025-10-10T12:56:52.826524Z", "logger": "posthog.geoip", "level": "error", "pid": 65403, "tid": 281466655207264, "exception": "Traceback (most recent call last):\n File "/code/posthog/geoip.py", line 52, in get_geoip_properties\n geoip_properties = geoip.city(ip_address)\n ^^^^^^^^^^^^^^^^^^^^^^\n File "/python-runtime/lib/python3.11/site-packages/django/contrib/gis/geoip2/base.py", line 181, in city\n return City(self._city.city(enc_query))\n ^^^^^^^^^^^^^^^^^^^^^^^^^^\n File "/python-runtime/lib/python3.11/site-packages/geoip2/database.py", line 150, in city\n return cast(City, self._model_for(geoip2.models.City, "City", ip_address))\n ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n File "/python-runtime/lib/python3.11/site-packages/geoip2/database.py", line 253, in _model_for\n (record, prefix_len) = self._get(types, ip_address)\n ^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n File "/python-runtime/lib/python3.11/site-packages/geoip2/database.py", line 240, in _get\n raise geoip2.errors.AddressNotFoundError(\ngeoip2.errors.AddressNotFoundError: The address 172.0.1.1 is not in the database."}',
                level: 'error',
            },
            {
                message: `{"request_id": "8cbf3d86-5270-4129-a9a7-5c0908a6a806", "ip": "1.0.0.1", "request": "<ASGIRequest: OPTIONS '/array/123/config'>", "user_agent": "Mozilla/5.0 (iPad; CPU OS 18_6_2 like Mac OS X) AppleWebKit/605.1.15", "event": "request_started",  "host": "us-assets.i.posthog.com", "container_hostname": "posthog-web-django-c5f54bd98-z2kjj", "timestamp": "2025-10-10T12:58:08.090793Z", "logger": "django_structlog.middlewares.request", "level": "info", "pid": 44582, "tid": 281465917009760}`,
                level: 'info',
            },
            {
                message:
                    '/python-runtime/lib/python3.11/site-packages/django/http/response.py:517: Warning: StreamingHttpResponse must consume synchronous iterators in order to serve them asynchronously. Use an asynchronous iterator instead.',
                level: 'warn',
            },
        ],
    },
    'cdp-events-consumer': {
        attributes: {
            'k8s.namespace.name': 'posthog',
            'service.name': 'cdp-events-consumer',
            'k8s.pod.name': 'cdp-events-consumer',
            'k8s.container.name': 'cdp-events-consumer',
        },
        logs: [
            {
                message: '[CDP-PROCESSED-EVENTS] 🔁 CdpEventsConsumer - handling batch',
                level: 'info',
                attributes: {
                    size: '100',
                },
            },
            {
                message: '[CDP-PROCESSED-EVENTS] 🦔 [HogFunction] Filter took longer than expected',
                level: 'warn',
                attributes: {
                    hog_function_id: '123',
                    hog_function_name: 'Filter fail test',
                    duration: '1000',
                },
            },
        ],
    },
}

// Make a deterministic log of all messages. We basicallty want to create a tonne of logs over an example time period with some deterministic randomness to it.

const generateLogs = (): LogMessage[] => {
    const results: LogMessage[] = []
    const startTime = dayjs().utc().subtract(48, 'hours')
    const endTime = dayjs().utc()
    // Iterate each minute adding N logs to the results
    let currentTime = startTime

    while (currentTime.isBefore(endTime)) {
        Object.values(EXAMPLES).forEach((example) => {
            const logsToAdd = Math.floor(deterministicRandom() * 10)
            for (let i = 0; i < logsToAdd; i++) {
                const log = sampleOne<(typeof example.logs)[0]>(example.logs)
                results.push({
                    uuid: uuid(),
                    trace_id: uuid(),
                    span_id: uuid(),
                    resource_attributes: 'any',
                    body: log.message,
                    attributes: {
                        ...example.attributes,
                        ...log.attributes,
                    },
                    timestamp: currentTime.toISOString(),
                    observed_timestamp: currentTime.toISOString(),
                    severity_text: log.level,
                    severity_number: 13,
                    level: log.level,
                    instrumentation_scope: 'any',
                    event_name: 'any',
                })
            }
        })
        currentTime = currentTime.add(1, 'minutes')
    }

    return results
}

let _cachedLogs: LogMessage[] | null = null

const getLogs = async (
    body: any
): Promise<{
    startTime: dayjs.Dayjs
    endTime: dayjs.Dayjs
    logs: LogMessage[]
}> => {
    if (!_cachedLogs?.length) {
        _cachedLogs = generateLogs()
    }
    const ALL_LOGS_GENERATED = _cachedLogs
    const severityLevels = body.query?.severityLevels ?? []

    const startDate = dateStringToDayJs(body.query?.dateRange?.date_from ?? null) ?? dayjs().subtract(30, 'minutes')
    const endDate = dateStringToDayJs(body.query?.dateRange?.date_to ?? null) ?? dayjs()

    const logs = ALL_LOGS_GENERATED.filter((log) => {
        if (startDate && startDate.isAfter(dayjs(log.timestamp))) {
            return false
        }
        if (endDate && endDate.isBefore(dayjs(log.timestamp))) {
            return false
        }
        if (body.query?.serviceNames?.length && !body.query?.serviceNames.includes(log.attributes['service.name'])) {
            return false
        }
        if (severityLevels.length && !severityLevels.includes(log.severity_text.toLowerCase())) {
            return false
        }
        return true
    })

    return {
        startTime: startDate,
        endTime: endDate,
        logs,
    }
}

const queryMock: MockSignature = async (req, res, ctx) => {
    await delayIfNotTestRunner()

    const body = await req.json()
    const { logs } = await getLogs(body)

    const limit = body.query?.limit ?? 100
    const offset = body.query?.offset ?? 0

    const results = logs.slice(offset, offset + limit)

    return res(ctx.json({ results: results }))
}

const sparklineMock: MockSignature = async (req, res, ctx) => {
    await delayIfNotTestRunner()
    const body = await req.json()
    const { startTime, endTime, logs } = await getLogs(body)

    // Interval selection
    const hoursSpan = endTime.diff(startTime, 'hours', true)
    let intervalMins = 1
    if (hoursSpan >= 12 && hoursSpan < 24) {
        intervalMins = 5
    } else if (hoursSpan >= 24 * 7) {
        intervalMins = 60
    }

    // Build buckets
    type Counts = { info: number; warn: number; error: number; total: number }
    const bucketMap = new Map<string, Counts>()

    // Pre-seed buckets so we include empty intervals
    let cursor = startTime.startOf('minute')
    const endCursor = endTime.startOf('minute')
    while (cursor.isBefore(endCursor)) {
        const key = cursor.toISOString()
        bucketMap.set(key, { info: 0, warn: 0, error: 0, total: 0 })
        cursor = cursor.add(intervalMins, 'minute')
    }

    // Assign logs to buckets
    for (const log of logs) {
        const ts = dayjs(log.timestamp)
        if (ts.isBefore(startTime) || !ts.isBefore(endTime)) {
            continue
        }

        const minsFromStart = ts.diff(startTime, 'minute')
        const bucketIndex = Math.floor(minsFromStart / intervalMins)
        const bucketStart = startTime.startOf('minute').add(bucketIndex * intervalMins, 'minute')
        const key = bucketStart.toISOString()

        const level = String(log.severity_text ?? log.level ?? 'info').toLowerCase()
        const counts = bucketMap.get(key)
        if (!counts) {
            continue
        }

        if (level === 'error') {
            counts.error += 1
        } else if (level === 'warn' || level === 'warning') {
            counts.warn += 1
        } else {
            counts.info += 1
        }
        counts.total += 1
    }

    const results: { count: number; level: string; time: string }[] = []

    // Emit ordered response
    Array.from(bucketMap.entries())
        .sort(([a], [b]) => (a < b ? -1 : 1))
        .forEach(([timestamp, counts]) =>
            Object.entries(counts).forEach(([level, count]) => {
                results.push({
                    count: count,
                    level: level,
                    time: timestamp,
                })
            })
        )

    return res(ctx.json(results))
}

const attributesMock: MockSignature = async (_req, res, ctx) => {
    await delayIfNotTestRunner()
    const results = Object.keys(keysAndValues).map((key) => ({
        id: key,
        name: key,
    }))
    return res(ctx.json(results))
}

const valuesMock: MockSignature = async (req, res, ctx) => {
    await delayIfNotTestRunner()
    const key = req.url.searchParams.get('key') ?? ''
    const results = (keysAndValues[key] ?? []).map((value) => ({
        id: value,
        name: value,
    }))
    return res(ctx.json(results))
}

export default {
    title: 'Scenes-App/Logs',
    decorators: [
        // mocks used by all stories in this file
        mswDecorator({
            get: {
                '/api/environments/:team_id/logs/attributes': attributesMock,
                '/api/environments/:team_id/logs/values': valuesMock,
            },
            post: {
                '/api/environments/:team_id/logs/query': queryMock,
                '/api/environments/:team_id/logs/sparkline': sparklineMock,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        mockDate: '2023-02-18',
    }, // scene mode
} as Meta

export function LogsScene(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.logs())
    }, [])
    return <App />
}
