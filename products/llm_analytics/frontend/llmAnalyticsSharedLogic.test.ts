import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { buildApplyUrlStatePayload } from './llmAnalyticsSharedLogic'

describe('buildApplyUrlStatePayload', () => {
    const currentDateFilter = { dateFrom: '-1h', dateTo: null }
    const currentPropertyFilters: AnyPropertyFilter[] = []

    it('flags datesChanged=true when dateFrom differs', () => {
        const payload = buildApplyUrlStatePayload({
            dateFrom: '-7d',
            dateTo: null,
            shouldFilterTestAccounts: false,
            propertyFilters: [],
            currentDateFilter,
            currentPropertyFilters,
        })
        expect(payload.datesChanged).toBe(true)
    })

    it('flags datesChanged=true when dateTo differs', () => {
        const payload = buildApplyUrlStatePayload({
            dateFrom: '-1h',
            dateTo: '2026-04-01',
            shouldFilterTestAccounts: false,
            propertyFilters: [],
            currentDateFilter,
            currentPropertyFilters,
        })
        expect(payload.datesChanged).toBe(true)
    })

    it('flags datesChanged=false when both dates match current', () => {
        const payload = buildApplyUrlStatePayload({
            dateFrom: '-1h',
            dateTo: null,
            shouldFilterTestAccounts: true,
            propertyFilters: [],
            currentDateFilter,
            currentPropertyFilters,
        })
        expect(payload.datesChanged).toBe(false)
    })

    it('preserves propertyFilters reference when contents equal', () => {
        const existing: AnyPropertyFilter[] = [
            {
                type: PropertyFilterType.Event,
                key: '$ai_model',
                operator: PropertyOperator.Exact,
                value: ['gpt-4o'],
            },
        ]
        const equivalentCopy: AnyPropertyFilter[] = [
            {
                type: PropertyFilterType.Event,
                key: '$ai_model',
                operator: PropertyOperator.Exact,
                value: ['gpt-4o'],
            },
        ]
        const payload = buildApplyUrlStatePayload({
            dateFrom: '-1h',
            dateTo: null,
            shouldFilterTestAccounts: false,
            propertyFilters: equivalentCopy,
            currentDateFilter,
            currentPropertyFilters: existing,
        })
        expect(payload.propertyFilters).toBe(existing)
    })

    it('returns new propertyFilters reference when contents differ', () => {
        const existing: AnyPropertyFilter[] = []
        const next: AnyPropertyFilter[] = [
            {
                type: PropertyFilterType.Event,
                key: '$ai_model',
                operator: PropertyOperator.Exact,
                value: ['gpt-4o'],
            },
        ]
        const payload = buildApplyUrlStatePayload({
            dateFrom: '-1h',
            dateTo: null,
            shouldFilterTestAccounts: false,
            propertyFilters: next,
            currentDateFilter,
            currentPropertyFilters: existing,
        })
        expect(payload.propertyFilters).toBe(next)
    })

    it('passes through shouldFilterTestAccounts and date values unchanged', () => {
        const payload = buildApplyUrlStatePayload({
            dateFrom: '-30d',
            dateTo: '-1d',
            shouldFilterTestAccounts: true,
            propertyFilters: [],
            currentDateFilter,
            currentPropertyFilters,
        })
        expect(payload.dateFrom).toBe('-30d')
        expect(payload.dateTo).toBe('-1d')
        expect(payload.shouldFilterTestAccounts).toBe(true)
    })
})
