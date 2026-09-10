import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { EventPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { ErrorTrackingIssueSeverityRuleEnumApi } from '../../../generated/api.schemas'
import { ErrorTrackingSeverityRule, ErrorTrackingRuleType } from '../rules/types'
import { severityRuleModalLogic } from './severityRuleModalLogic'

const browserFilter: EventPropertyFilter = {
    key: '$browser',
    value: ['Firefox'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

const persistedRule: ErrorTrackingSeverityRule = {
    id: 'rule-id',
    filters: { type: FilterLogicalOperator.And, values: [browserFilter] },
    severity: ErrorTrackingIssueSeverityRuleEnumApi.High,
    order_key: 0,
    disabled_data: null,
    created_at: '2026-08-13T00:00:00Z',
    updated_at: '2026-08-13T00:00:00Z',
}

describe('severityRuleModalLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api, 'query').mockResolvedValue({ results: [[3, 2]] } as any)
        jest.spyOn(api.errorTracking, 'rules').mockResolvedValue({ results: [] })
        jest.spyOn(api.errorTracking, 'createRule').mockResolvedValue(persistedRule)
        jest.spyOn(api.errorTracking, 'updateRule').mockResolvedValue()
        jest.spyOn(api.errorTracking, 'deleteRule').mockResolvedValue()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('requires a supported severity and creates a rule', async () => {
        const logic = severityRuleModalLogic()
        logic.mount()

        logic.actions.openModal()
        expect(logic.values.hasSeverity).toBe(false)
        logic.actions.updateSeverity(ErrorTrackingIssueSeverityRuleEnumApi.Critical)
        expect(logic.values.hasSeverity).toBe(true)

        await expectLogic(logic, () => logic.actions.saveRule()).toFinishAllListeners()

        expect(api.errorTracking.createRule).toHaveBeenCalledWith(
            ErrorTrackingRuleType.Severity,
            expect.objectContaining({ severity: ErrorTrackingIssueSeverityRuleEnumApi.Critical })
        )
        logic.unmount()
    })

    it('edits and deletes a persisted rule', async () => {
        const logic = severityRuleModalLogic()
        logic.mount()

        logic.actions.openModal(persistedRule)
        logic.actions.updateSeverity(ErrorTrackingIssueSeverityRuleEnumApi.Low)
        await expectLogic(logic, () => logic.actions.saveRule()).toFinishAllListeners()
        expect(api.errorTracking.updateRule).toHaveBeenCalledWith(
            ErrorTrackingRuleType.Severity,
            expect.objectContaining({ id: persistedRule.id, severity: ErrorTrackingIssueSeverityRuleEnumApi.Low })
        )

        logic.actions.openModal(persistedRule)
        await expectLogic(logic, () => logic.actions.deleteRule()).toFinishAllListeners()
        expect(api.errorTracking.deleteRule).toHaveBeenCalledWith(ErrorTrackingRuleType.Severity, persistedRule.id)
        logic.unmount()
    })

    it('previews matching exceptions with error tracking query tags', async () => {
        const logic = severityRuleModalLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.openModal(persistedRule)
            logic.actions.loadMatchCount()
        }).toFinishAllListeners()

        expect(api.query).toHaveBeenCalledWith(
            expect.objectContaining({
                tags: { productKey: ProductKey.ERROR_TRACKING },
                fixedProperties: [{ type: FilterLogicalOperator.And, values: [browserFilter] }],
            })
        )
        expect(logic.values.matchResult).toEqual({ exceptionCount: 3, issueCount: 2 })
        logic.unmount()
    })
})
