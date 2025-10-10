import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { MockSignature } from '~/mocks/utils'

const delayIfNotTestRunner = async (): Promise<void> => {
    await new Promise((resolve) => setTimeout(resolve, 200 + Math.random() * 1000))
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

const queryMock: MockSignature = async (req, res, ctx) => {
    await delayIfNotTestRunner()
    const results = []
    for (let i = 0; i < 1000; i++) {
        results.push({
            uuid: uuid(),
            trace_id: uuid(),
            span_id: uuid(),
            body: JSON.stringify({
                timestamp: '2025-10-10T12:03:28.093626Z',
                level: 'WARN',
                fields: {
                    message: 'Person properties not found in evaluation state cache',
                },
            }),
            attributes: {
                'k8s.pod.uid': uuid(),
                level: 'WARN',
                timestamp: '2025-10-10T12:03:28.093626Z',
                'k8s.namespace.name': 'posthog',
                'k8s.pod.start_time': '2025-10-10T08:36:19Z',
                'k8s.pod.name': 'posthog-web',
                'k8s.container.restart_count': '0',
                'k8s.node.name': 'node-1',
                'service.name': 'posthog-web',
                'k8s.container.name': 'posthog-web',
                'log.iostream': 'stdout',
            },
            timestamp: '2025-10-10T12:03:28.093711',
            observed_timestamp: '2025-10-10T12:03:28.435131',
            severity_text: 'warn',
            severity_number: 13,
            level: 'warn',
            resource_attributes: {},
            instrumentation_scope: '@',
            event_name: '',
        })
    }

    return res(ctx.json({ results }))
}

const sparklineMock: MockSignature = async (req, res, ctx) => {
    await delayIfNotTestRunner()
    const startTime = dayjs().subtract(30, 'minutes')
    const endTime = dayjs()
    const interval = 1000 * 60 // 1 minute
    const response = []

    let currentTime = startTime

    while (currentTime.isBefore(endTime)) {
        response.push({
            time: currentTime.format('YYYY-MM-DDTHH:mm:ssZ'),
            level: 'warn',
            count: 197999,
        })
        currentTime = currentTime.add(interval, 'ms')
    }

    return res(ctx.json(response))
}

const attributesMock: MockSignature = async (req, res, ctx) => {
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
