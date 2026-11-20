import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { metricNameError, saveSpanMetricLogic } from './saveSpanMetricLogic'
import {
    DERIVED_SPAN_DURATION,
    DERIVED_SPAN_ERRORS,
    DERIVED_SPAN_REQUESTS,
    buildSpanMetricRuleDraft,
} from './spanMetricRuleDraft'

const SERVER = { key: 'kind', operator: 'exact', value: '2', type: 'span_attribute' }
const ERROR = { key: 'status_code', operator: 'exact', value: '2', type: 'span_attribute' }
const API_SERVICE = { key: 'service_name', operator: 'exact', value: 'api', type: 'span_attribute' }

const leaves = (draft: ReturnType<typeof buildSpanMetricRuleDraft>): unknown[] =>
    (draft!.rule.filter_group as { values: { values: unknown[] }[] }).values[0].values

describe('save a span query as a metric', () => {
    it.each([
        ['requests count server spans', DERIVED_SPAN_REQUESTS, null, [API_SERVICE, SERVER], 'spans.api.requests'],
        [
            'errors add an error status filter',
            DERIVED_SPAN_ERRORS,
            null,
            [API_SERVICE, SERVER, ERROR],
            'spans.api.errors',
        ],
        [
            'duration records a distribution',
            DERIVED_SPAN_DURATION,
            'duration_ms',
            [API_SERVICE, SERVER],
            'spans.api.duration',
        ],
    ])('%s', (_name, metricName, valueAttribute, expectedFilters, expectedMetricName) => {
        const draft = buildSpanMetricRuleDraft(metricName, [{ key: 'service.name', op: 'eq', value: 'api' }], [])

        expect(draft?.rule).toMatchObject({
            source: 'spans',
            value_attribute: valueAttribute,
            metric_name: expectedMetricName,
        })
        expect(leaves(draft)).toEqual(expectedFilters)
        expect(draft?.addsServerFilter).toBe(true)
    })

    it('maps span dimensions to the keys the rule matches and warns about what it drops', () => {
        const draft = buildSpanMetricRuleDraft(
            DERIVED_SPAN_REQUESTS,
            [
                { key: 'span.kind', op: 'eq', value: 'client' },
                { key: 'span.status_code', op: 'regex', value: 'error|unset' },
                { key: 'deployment.environment', op: 'neq', value: 'staging' },
                { key: 'http.route', op: 'regex', value: '^/api' },
            ],
            ['span.name', 'service.version', 'k8s.namespace.name', 'http.route']
        )

        // A span.kind filter in the query replaces the server-span default. A negative filter
        // also accepts spans without the attribute, as the chart does.
        const environment = { key: 'deployment.environment', operator: 'is_not', value: 'staging' }
        expect(leaves(draft)).toEqual([
            { key: 'kind', operator: 'exact', value: '3', type: 'span_attribute' },
            {
                type: 'OR',
                values: [
                    { ...environment, type: 'span_resource_attribute' },
                    { key: 'deployment.environment', operator: 'is_not_set', type: 'span_resource_attribute' },
                ],
            },
            { key: 'http.route', operator: 'regex', value: '^/api', type: 'span_attribute' },
        ])
        expect(draft?.addsServerFilter).toBe(false)
        expect(draft?.ignoresCase).toBe(true)
        expect(draft?.droppedFilters).toEqual(['span.status_code regex error|unset'])
        expect(draft?.rule.group_by).toEqual([
            'name',
            'resource_attributes.service.version',
            'resource_attributes.k8s.namespace.name',
            'attributes.http.route',
        ])
        expect(draft?.rule.metric_name).toEqual('spans.requests')
    })

    it('omits the filter group when every filter is dropped', () => {
        const draft = buildSpanMetricRuleDraft(
            DERIVED_SPAN_REQUESTS,
            [{ key: 'span.kind', op: 'regex', value: 'serv' }],
            []
        )

        expect(draft?.rule.filter_group).toBeNull()
        expect(draft?.droppedFilters).toEqual(['span.kind regex serv'])
    })

    it.each([['posthog.derived.spans.apdex'], ['posthog.derived.logs.records'], ['http_requests_total']])(
        'offers nothing for %s',
        (metricName) => {
            expect(buildSpanMetricRuleDraft(metricName, [], [])).toBeNull()
        }
    )

    it('creates an enabled span rule with the edited name', async () => {
        const requests: unknown[] = []
        useMocks({
            get: { '/api/projects/:team_id/logs/metric_rules/': { results: [] } },
            post: {
                '/api/projects/:team_id/logs/metric_rules/': async ({ request }) => {
                    requests.push(await request.json())
                    return { id: 'rule-1' }
                },
            },
        })
        initKeaTests()
        const logic = saveSpanMetricLogic()
        logic.mount()
        const draft = buildSpanMetricRuleDraft(DERIVED_SPAN_ERRORS, [], ['service.name'])!

        logic.actions.openSaveSpanMetric(draft)
        logic.actions.setMetricName('checkout.errors')
        logic.actions.submitSpanMetric()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests).toEqual([
            {
                name: 'All services errors',
                metric_name: 'checkout.errors',
                source: 'spans',
                value_attribute: null,
                enabled: true,
                group_by: ['service_name'],
                filter_group: { type: 'AND', values: [{ type: 'AND', values: [SERVER, ERROR] }] },
            },
        ])
        expect(logic.values.draft).toBeNull()
        logic.unmount()
    })

    it('keeps a reopened modal open when an earlier save finishes', async () => {
        let finishSave: () => void = () => {}
        useMocks({
            get: { '/api/projects/:team_id/logs/metric_rules/': { results: [] } },
            post: {
                '/api/projects/:team_id/logs/metric_rules/': () =>
                    new Promise((resolve) => {
                        finishSave = () => resolve([201, { id: 'rule-1' }])
                    }),
            },
        })
        initKeaTests()
        const logic = saveSpanMetricLogic()
        logic.mount()
        const draft = buildSpanMetricRuleDraft(DERIVED_SPAN_REQUESTS, [], [])!

        logic.actions.openSaveSpanMetric(draft)
        logic.actions.submitSpanMetric()
        logic.actions.closeSaveSpanMetric()
        logic.actions.openSaveSpanMetric(draft)
        logic.actions.setMetricName('second.requests')
        await expectLogic(logic).delay(0)
        finishSave()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.draft).toBe(draft)
        expect(logic.values.metricName).toEqual('second.requests')
        logic.unmount()
    })

    it.each([
        ['', 'Enter a metric name.'],
        ['1spans', 'Start with a letter and use only letters, digits, dots, underscores and dashes.'],
        ['posthog.derived.spans.mine', 'Names starting with posthog.derived. are reserved.'],
    ])('blocks the name %p', (name, error) => {
        expect(metricNameError(name)).toEqual(error)
    })
})
