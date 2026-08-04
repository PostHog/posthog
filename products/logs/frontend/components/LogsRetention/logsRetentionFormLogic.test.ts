import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator } from '~/types'

import { LogsRetentionRuleApi } from 'products/logs/frontend/generated/api.schemas'

import {
    buildRetentionConfigPayload,
    buildRetentionFormDefaults,
    LogsRetentionFormType,
    logsRetentionFormLogic,
} from './logsRetentionFormLogic'

const mockSuggestName: jest.Mock<Promise<{ name: string }>, [string, unknown]> = jest.fn()

jest.mock('products/logs/frontend/generated/api', () => ({
    ...jest.requireActual<Record<string, unknown>>('products/logs/frontend/generated/api'),
    logsRetentionRulesSuggestNameCreate: (projectId: string, body: unknown) => mockSuggestName(projectId, body),
}))

const form = (overrides: Partial<LogsRetentionFormType> = {}): LogsRetentionFormType => ({
    name: 'keep api logs',
    enabled: true,
    retention_days: 30,
    filter_group: {
        type: FilterLogicalOperator.And,
        values: [{ key: 'service.name', type: 'log_resource_attribute', operator: 'exact', value: 'api' } as never],
    },
    ...overrides,
})

describe('logsRetentionFormLogic', () => {
    it('serializes retention_days and wraps the filter group in the stored envelope', () => {
        const config = buildRetentionConfigPayload(form())
        expect(config.retention_days).toEqual(30)
        // The ingestion worker unwraps a single-element AND envelope; the API stores it wrapped.
        expect(config.filter_group).toEqual({
            type: FilterLogicalOperator.And,
            values: [form().filter_group],
        })
    })

    it('round-trips a stored rule back into the form (unwraps the envelope, keeps the tier)', () => {
        const rule = {
            name: 'keep api logs',
            enabled: true,
            config: buildRetentionConfigPayload(form()),
        } as unknown as LogsRetentionRuleApi

        const defaults = buildRetentionFormDefaults(rule)
        expect(defaults.retention_days).toEqual(30)
        expect(defaults.filter_group).toEqual(form().filter_group)
    })

    it('falls back to the default tier when a stored rule has a non-tier retention value', () => {
        const rule = {
            name: 'legacy',
            enabled: false,
            config: { retention_days: 45, filter_group: { type: 'AND', values: [] } },
        } as unknown as LogsRetentionRuleApi

        expect(buildRetentionFormDefaults(rule).retention_days).toEqual(14)
    })
})

describe('logsRetentionFormLogic name suggestion', () => {
    const EMPTY_GROUP = { type: FilterLogicalOperator.And, values: [] }
    const EXISTING_RULE = { id: 'rule-1', name: 'keep api logs', enabled: true, config: {} } as LogsRetentionRuleApi

    let logic: ReturnType<typeof logsRetentionFormLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockSuggestName.mockClear()
        mockSuggestName.mockResolvedValue({ name: 'Keep api logs for 30 days' })
    })

    afterEach(() => {
        logic?.unmount()
    })

    const mountNew = (): void => {
        logic = logsRetentionFormLogic({ rule: null })
        logic.mount()
    }

    it('suggests a name when the filter group changes on a new rule', async () => {
        mountNew()
        await expectLogic(logic, () => {
            logic.actions.setRetentionFormValue('filter_group', form().filter_group)
        })
            .toDispatchActions(['refreshSuggestedName', 'loadSuggestedName', 'loadSuggestedNameSuccess'])
            .toMatchValues({ suggestedName: { fingerprint: expect.any(String), name: 'Keep api logs for 30 days' } })
        expect(mockSuggestName).toHaveBeenCalledTimes(1)
    })

    it('suggests a name when the retention tier changes', async () => {
        mountNew()
        await expectLogic(logic, () => {
            logic.actions.setRetentionFormValue('filter_group', form().filter_group)
        }).toDispatchActions(['loadSuggestedNameSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setRetentionFormValue('retention_days', 30)
        }).toDispatchActions(['refreshSuggestedName', 'loadSuggestedNameSuccess'])
        expect(mockSuggestName).toHaveBeenCalledTimes(2)
    })

    it('never suggests when editing an existing rule', async () => {
        logic = logsRetentionFormLogic({ rule: EXISTING_RULE })
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.setRetentionFormValue('filter_group', form().filter_group)
        }).toNotHaveDispatchedActions(['refreshSuggestedName'])
        expect(mockSuggestName).not.toHaveBeenCalled()
    })

    it('does not call the API for an empty filter group', async () => {
        mountNew()
        await expectLogic(logic, () => {
            logic.actions.setRetentionFormValue('filter_group', EMPTY_GROUP)
        })
            .toDispatchActions(['loadSuggestedNameSuccess'])
            .toMatchValues({ suggestedName: null })
        expect(mockSuggestName).not.toHaveBeenCalled()
    })

    it('never overwrites the name until the suggestion is explicitly used', async () => {
        mountNew()
        logic.actions.setRetentionFormValue('name', 'my own name')
        await expectLogic(logic, () => {
            logic.actions.setRetentionFormValue('filter_group', form().filter_group)
        }).toDispatchActions(['loadSuggestedNameSuccess'])
        expect(logic.values.retentionForm.name).toEqual('my own name')

        logic.actions.applySuggestedName()
        expect(logic.values.retentionForm.name).toEqual('Keep api logs for 30 days')
    })

    it('hides the suggestion silently when the request is throttled', async () => {
        mockSuggestName.mockRejectedValue({ status: 429, detail: 'Request was throttled' })
        mountNew()
        await expectLogic(logic, () => {
            logic.actions.setRetentionFormValue('filter_group', form().filter_group)
        })
            .toDispatchActions(['loadSuggestedNameSuccess'])
            .toNotHaveDispatchedActions(['loadSuggestedNameFailure'])
        expect(logic.values.suggestedName).toBeNull()
    })

    it('does not re-request when nothing feeding the prompt changed', async () => {
        mountNew()
        await expectLogic(logic, () => {
            logic.actions.setRetentionFormValue('filter_group', form().filter_group)
        }).toDispatchActions(['loadSuggestedNameSuccess'])

        await expectLogic(logic, () => {
            logic.actions.refreshSuggestedName()
        }).toDispatchActions(['loadSuggestedNameSuccess'])
        expect(mockSuggestName).toHaveBeenCalledTimes(1)
    })
})
