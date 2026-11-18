import { initKeaTests } from '~/test/init'

import { logsRetentionSectionLogic } from 'products/logs/frontend/components/LogsRetention/logsRetentionSectionLogic'
import { LOGS_RETENTION_PRODUCT } from 'products/logs/frontend/components/LogsRetention/retentionRulesProduct'

import { TRACES_RETENTION_PRODUCT } from './tracingRetentionProduct'

const mockLogsList = jest.fn().mockResolvedValue({ results: [] })
const mockTracingList = jest.fn().mockResolvedValue({ results: [] })

jest.mock('products/logs/frontend/generated/api', () => ({
    ...jest.requireActual<Record<string, unknown>>('products/logs/frontend/generated/api'),
    logsRetentionRulesList: (projectId: string) => mockLogsList(projectId),
}))
jest.mock('products/tracing/frontend/generated/api', () => ({
    ...jest.requireActual<Record<string, unknown>>('products/tracing/frontend/generated/api'),
    tracingRetentionRulesList: (projectId: string) => mockTracingList(projectId),
}))

describe('TRACES_RETENTION_PRODUCT', () => {
    beforeEach(() => {
        initKeaTests()
        mockLogsList.mockClear()
        mockTracingList.mockClear()
    })

    it('points at the span route, not the log one', () => {
        expect(TRACES_RETENTION_PRODUCT.source).toEqual('spans')
        expect(TRACES_RETENTION_PRODUCT.urls.newRule()).toContain('/tracing/')
        expect(TRACES_RETENTION_PRODUCT.urls.settings()).toContain('environment-tracing')
    })

    it('offers the span property vocabulary, with no log groups', () => {
        expect(TRACES_RETENTION_PRODUCT.taxonomicGroupTypes).toEqual([
            'spans',
            'span_resource_attributes',
            'span_attributes',
        ])
        expect(TRACES_RETENTION_PRODUCT.taxonomicGroupTypes).not.toEqual(LOGS_RETENTION_PRODUCT.taxonomicGroupTypes)
    })

    it('loads rules from the span route when the section is mounted with it', async () => {
        // The shared logic must never fall back to the logs route for a traces mount — that
        // would quietly show and edit the wrong product's rules.
        const logic = logsRetentionSectionLogic({ product: TRACES_RETENTION_PRODUCT })
        logic.mount()
        await logic.actions.loadRules()

        expect(mockTracingList).toHaveBeenCalled()
        expect(mockLogsList).not.toHaveBeenCalled()
        logic.unmount()
    })
})
