import { Meta } from '@storybook/react'
import { combineUrl, router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { sampleOne } from 'lib/utils/arrays'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { inStorybookTestRunner, uuid } from 'lib/utils/dom'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { MockSignature } from '~/mocks/utils'
import { LogMessage, LogSeverityLevel } from '~/queries/schema/schema-general'
import { PropertyFilterType } from '~/types'

import {
    FacetFilterTarget,
    FacetSelection,
    SERVICE_NAME_FILTER,
    SEVERITY_LEVEL_FILTER,
    facetSelection,
    setFacetSelection,
} from 'products/logs/frontend/components/LogsViewer/FacetRail/facetFilters'

function createSeededRandom(seed: number): () => number {
    // LCG constants from Numerical Recipes
    let m = 0x80000000 // 2^31
    let a = 1103515245
    let c = 12345

    let state = seed ? seed : Math.floor(Math.random() * (m - 1))

    return function () {
        state = (a * state + c) % m
        return state / m
    }
}

const deterministicRandom = createSeededRandom(1234)

const EMPTY_SELECTION: FacetSelection = { included: [], excluded: [] }

const delayIfNotTestRunner = async (): Promise<void> => {
    await new Promise((resolve) => setTimeout(resolve, inStorybookTestRunner() ? 0 : 200 + Math.random() * 1000))
}

const attributeExamples: Record<
    PropertyFilterType.LogAttribute | PropertyFilterType.LogResourceAttribute,
    Record<string, string[]>
> = {
    [PropertyFilterType.LogResourceAttribute]: {
        'service.name': [
            'posthog-web',
            'posthog-feature-flags',
            'posthog-surveys',
            'posthog-web-django',
            'cdp-precalculated-filters-consumer',
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
            'cdp-precalculated-filters-consumer',
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
    },
    [PropertyFilterType.LogAttribute]: {
        'log.iostream': ['stdout', 'stderr'],
        duration: ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10'],
        method: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD'],
    },
}

const EXAMPLES: Record<
    string,
    {
        resource_attributes: Record<string, string>
        logs: { message: string; level: LogSeverityLevel; attributes?: Record<string, string> }[]
    }
> = {
    'posthog-web': {
        resource_attributes: {
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
        resource_attributes: {
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

// Make a deterministic log of all messages. We basically want to create a tonne of logs over an example time period with some deterministic randomness to it.

const generateLogs = (): LogMessage[] => {
    const results: LogMessage[] = []
    const startTime = inStorybookTestRunner()
        ? dayjs().utc().subtract(15, 'minutes')
        : dayjs().utc().subtract(1, 'hours')
    const endTime = dayjs().utc()
    // Iterate each minute adding N logs to the results
    let currentTime = startTime

    while (currentTime.isBefore(endTime)) {
        Object.values(EXAMPLES).forEach((example) => {
            const logsToAdd = Math.floor(deterministicRandom() * 3)
            for (let i = 0; i < logsToAdd; i++) {
                const log = sampleOne<(typeof example.logs)[0]>(example.logs)
                results.push({
                    uuid: uuid(),
                    trace_id: uuid(),
                    span_id: uuid(),
                    resource_attributes: example.resource_attributes,
                    body: log.message,
                    attributes: { ...log.attributes },
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
    const levels = facetSelection(body.query?.filterGroup, SEVERITY_LEVEL_FILTER)
    const services = facetSelection(body.query?.filterGroup, SERVICE_NAME_FILTER)

    const startDate = dateStringToDayJs(body.query?.dateRange?.date_from ?? null) ?? dayjs().subtract(30, 'minutes')
    const endDate = dateStringToDayJs(body.query?.dateRange?.date_to ?? null) ?? dayjs()

    const logs = ALL_LOGS_GENERATED.filter((log) => {
        if (startDate && startDate.isAfter(dayjs(log.timestamp))) {
            return false
        }
        if (endDate && endDate.isBefore(dayjs(log.timestamp))) {
            return false
        }
        const service = log.resource_attributes['service.name']
        if (services.included.length && !services.included.includes(service)) {
            return false
        }
        if (services.excluded.includes(service)) {
            return false
        }
        const level = log.severity_text.toLowerCase()
        if (levels.included.length && !levels.included.includes(level)) {
            return false
        }
        if (levels.excluded.includes(level)) {
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

const queryMock: MockSignature = async ({ request }) => {
    await delayIfNotTestRunner()

    const body = (await request.json()) as Record<string, any>
    const { logs } = await getLogs(body)

    const limit = body.query?.limit ?? 100
    const offset = body.query?.offset ?? 0

    const results = logs.slice(offset, offset + limit)

    return [200, { results: results, maxExportableLogs: 5000 }]
}

const sparklineMock: MockSignature = async ({ request }) => {
    await delayIfNotTestRunner()
    const body = (await request.json()) as Record<string, any>
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

    return [200, results]
}

/**
 * Facet values + counts for the rail, computed over the same generated logs the viewer is showing so
 * the counts and the rows agree. Cross-filtering is the backend's job: it strips the faceted field's
 * own filter, which here means faceting on a field ignores that field's selection but honors the rest.
 */
const facetValuesMock: MockSignature = async ({ request }) => {
    await delayIfNotTestRunner()
    const body = (await request.json()) as Record<string, any>
    const facetField = body.query?.facetField
    const resourceAttribute = body.query?.facetResourceAttribute
    // Strip the filter belonging to the facet being queried, whichever facet that is. Picking the
    // wrong one inverts the contract: the facet would zero out its own selected value and keep
    // counting rows another facet has filtered away.
    const own: FacetFilterTarget | null =
        facetField === 'service_name'
            ? SERVICE_NAME_FILTER
            : facetField === 'severity_text'
              ? SEVERITY_LEVEL_FILTER
              : resourceAttribute
                ? { key: resourceAttribute, type: PropertyFilterType.LogResourceAttribute }
                : null
    const scopedGroup = own ? setFacetSelection(body.query?.filterGroup, own, EMPTY_SELECTION) : body.query?.filterGroup
    const { logs } = await getLogs({ query: { ...body.query, filterGroup: scopedGroup } })

    const counts = new Map<string, number>()
    for (const log of logs) {
        const value =
            facetField === 'service_name'
                ? log.resource_attributes['service.name']
                : facetField === 'severity_text'
                  ? log.severity_text.toLowerCase()
                  : log.resource_attributes[resourceAttribute]
        if (value) {
            counts.set(String(value), (counts.get(String(value)) ?? 0) + 1)
        }
    }

    const search = String(body.query?.facetSearch ?? '').toLowerCase()
    const results = Array.from(counts.entries())
        .filter(([value]) => !search || value.toLowerCase().includes(search))
        .sort(([, a], [, b]) => b - a)
        .map(([value, count]) => ({ value, count }))
    return [200, { results }]
}

// The taxonomic filter asks for `attribute_type=log|resource` and reads a paginated list whose items
// carry their own propertyFilterType (see the Log attributes / Resource attributes groups in
// taxonomicFilterLogic). Answering any other shape leaves those groups empty in the picker.
function attributeTypeOf(request: Request): PropertyFilterType.LogAttribute | PropertyFilterType.LogResourceAttribute {
    return new URL(request.url).searchParams.get('attribute_type') === 'resource'
        ? PropertyFilterType.LogResourceAttribute
        : PropertyFilterType.LogAttribute
}

const attributesMock: MockSignature = async ({ request }) => {
    await delayIfNotTestRunner()
    const type = attributeTypeOf(request)
    const search = (new URL(request.url).searchParams.get('search') ?? '').toLowerCase()
    const results = Object.keys(attributeExamples[type])
        .filter((key) => !search || key.toLowerCase().includes(search))
        .map((name) => ({ name, propertyFilterType: type, matchedOn: 'key' }))
    return [200, { results, count: results.length }]
}

const valuesMock: MockSignature = async ({ request }) => {
    await delayIfNotTestRunner()
    const url = new URL(request.url)
    const key = url.searchParams.get('key') ?? ''
    const type = attributeTypeOf(request)
    const results = (attributeExamples[type][key] ?? []).map((value) => ({
        id: value,
        name: value,
    }))
    return [200, results]
}

// Synthetic per-service aggregates for the Services tab: a realistic head of
// named services and a long generated tail, so pagination and the truncation
// banner both render.
const SERVICE_HEAD: [string, number, number][] = [
    // [name, log_count, error_rate]
    ['checkout-api', 4_182_330, 0.0021],
    ['ingestion-worker', 3_411_089, 0.0004],
    ['payments-gateway', 2_207_555, 0.1391],
    ['email-renderer', 1_876_002, 0.0102],
    ['session-recorder', 1_412_776, 0.0009],
    ['feature-flag-evaluator', 988_120, 0.0001],
    ['batch-exporter', 745_990, 0.0356],
    ['webhook-dispatcher', 512_304, 0.0044],
]

const SERVICES_FIXTURE = [
    ...SERVICE_HEAD,
    ...Array.from({ length: 992 }, (_, i): [string, number, number] => [
        `batch-worker-${String(i + 1).padStart(3, '0')}`,
        400_000 - i * 400,
        0.001,
    ]),
].map(([service_name, log_count, error_rate]) => {
    const error_count = Math.round(log_count * error_rate)
    const warn = Math.round(log_count * 0.05)
    const debug = Math.round(log_count * 0.2)
    return {
        service_name,
        log_count,
        error_count,
        error_rate,
        severity_breakdown: { debug, info: log_count - debug - warn - error_count, warn, error: error_count },
        active_rules: [],
    }
})

const servicesMock: MockSignature = async ({ request }) => {
    await delayIfNotTestRunner()
    const body = (await request.json()) as Record<string, any>
    const query = body.query ?? {}

    let services = SERVICES_FIXTURE
    if (query.serviceNameSearch) {
        const term = String(query.serviceNameSearch).toLowerCase()
        services = services.filter((s) => s.service_name.toLowerCase().includes(term))
    }
    const totalServices = services.length + (query.serviceNameSearch ? 0 : 287) // pretend a tail beyond the cap exists
    if (query.serviceNames?.length) {
        services = services.filter((s) => query.serviceNames.includes(s.service_name))
    }
    services = services.slice(0, 1000)

    const totalLogs = services.reduce((acc, s) => acc + s.log_count, 0)
    const sparklineFor = services.slice(0, 25)
    const sparkline = sparklineFor.flatMap((s) =>
        Array.from({ length: 24 }, (_, hour) => ({
            time: dayjs('2023-02-17T00:00:00Z').add(hour, 'hour').toISOString(),
            service_name: s.service_name,
            count: Math.max(1, Math.round((s.log_count / 24) * (0.6 + 0.8 * Math.abs(Math.sin(hour + s.log_count))))),
        }))
    )

    return [
        200,
        {
            services: services.map((s) => ({
                ...s,
                volume_share_pct: totalLogs ? Math.round((10000 * s.log_count) / totalLogs) / 100 : 0,
            })),
            sparkline,
            total_services: totalServices,
            summary: {
                top_services_count: Math.min(5, services.length),
                top_services_volume_share_pct: 68.4,
            },
        },
    ]
}

export default {
    title: 'Scenes-App/Logs',
    decorators: [
        // mocks used by all stories in this file
        // Endpoint prefix follows the caller: the generated client is project-scoped,
        // while the handwritten ApiRequest helpers are environment-scoped.
        mswDecorator({
            get: {
                // Both prefixes, because both callers exist: the taxonomic filter asks the
                // environment-scoped path, and facetPresenceLogic asks the project-scoped one through
                // the generated client. Answering only one empties the other's list.
                '/api/environments/:team_id/logs/attributes': attributesMock,
                '/api/projects/:team_id/logs/attributes': attributesMock,
                '/api/environments/:team_id/logs/values': valuesMock,
                '/api/environments/:team_id/logs/has_logs': () => [200, { hasLogs: true }],
            },
            post: {
                '/api/environments/:team_id/logs/query': queryMock,
                '/api/projects/:team_id/logs/facet_values': facetValuesMock,
                '/api/environments/:team_id/logs/sparkline': sparklineMock,
                '/api/projects/:team_id/logs/services': servicesMock,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        mockDate: '2023-02-18',
        testOptions: {
            waitForSelector: '[data-attr="logs-viewer"]',
        },
    }, // scene mode
    tags: ['test-skip'],
} as Meta

export function LogsScene(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.logs())
    }, [])
    return <App />
}
LogsScene.parameters = {
    featureFlags: [],
}

export function LogsSceneServicesTab(): JSX.Element {
    useEffect(() => {
        router.actions.push(combineUrl(urls.logs(), { activeTab: 'services' }).url)
    }, [])
    return <App />
}
// Story parameters replace the meta's rather than merging, so each list is complete.
LogsSceneServicesTab.parameters = {
    featureFlags: [FEATURE_FLAGS.LOGS_SERVICES_VIEW],
    testOptions: {
        waitForSelector: '.LemonTable',
    },
}

export function LogsSceneServicesTabV2(): JSX.Element {
    useEffect(() => {
        router.actions.push(combineUrl(urls.logs(), { activeTab: 'services' }).url)
    }, [])
    return <App />
}
LogsSceneServicesTabV2.parameters = {
    featureFlags: [FEATURE_FLAGS.LOGS_SERVICES_VIEW, FEATURE_FLAGS.LOGS_SERVICES_VIEW_V2],
    testOptions: {
        // v2-specific, so this fails rather than passes if the gate falls through to the v1 table.
        // A rendered row also means the virtualized list measured its container.
        waitForSelector: '[data-attr="logs-services-row"]',
    },
}
