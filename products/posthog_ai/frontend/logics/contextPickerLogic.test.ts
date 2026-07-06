import { expectLogic } from 'kea-test-utils'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { initKeaTests } from '~/test/init'

import { attachedContextLogic } from './attachedContextLogic'
import { PICKER_PROVIDER_ID, contextPickerLogic, taxonomicItemToAttachedContext } from './contextPickerLogic'

describe('contextPickerLogic', () => {
    let store: ReturnType<typeof attachedContextLogic.build>
    let logic: ReturnType<typeof contextPickerLogic.build>

    beforeEach(() => {
        initKeaTests()
        store = attachedContextLogic()
        store.mount()
        logic = contextPickerLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        store?.unmount()
    })

    test.each([
        [TaxonomicFilterGroupType.Events, { id: 'ev-uuid', name: '$pageview' }, 'event', 'ev-uuid', '$pageview'],
        [TaxonomicFilterGroupType.Actions, { id: 12, name: 'Signup' }, 'action', 12, 'Signup'],
        [TaxonomicFilterGroupType.Insights, { short_id: 'abc123', name: 'DAU' }, 'insight', 'abc123', 'DAU'],
        [TaxonomicFilterGroupType.Dashboards, { id: 7, name: 'Growth' }, 'dashboard', 7, 'Growth'],
        [TaxonomicFilterGroupType.Notebooks, { short_id: 'nb1', title: 'Notes' }, 'notebook', 'nb1', 'Notes'],
        [
            TaxonomicFilterGroupType.ErrorTrackingIssues,
            { id: 'issue-1', name: 'TypeError' },
            'error_tracking_issue',
            'issue-1',
            'TypeError',
        ],
    ])('taxonomicItemToAttachedContext maps %s', (groupType, item, type, key, label) => {
        expect(taxonomicItemToAttachedContext('fallback', groupType, item)).toEqual({ type, key, label })
    })

    it('returns null for group types the picker does not offer', () => {
        expect(
            taxonomicItemToAttachedContext('x', TaxonomicFilterGroupType.Cohorts, { id: 1, name: 'Cohort' })
        ).toBeNull()
    })

    it('picks flow into the store, removal and unmount take them back out', async () => {
        await expectLogic(logic, () => {
            logic.actions.handleTaxonomicFilterChange('abc123', TaxonomicFilterGroupType.Insights, {
                short_id: 'abc123',
                name: 'DAU',
            })
        }).toFinishAllListeners()
        expect(store.values.contextItems).toEqual([{ type: 'insight', key: 'abc123', label: 'DAU' }])

        await expectLogic(logic, () => {
            logic.actions.removePickedItem('insight:abc123')
        }).toFinishAllListeners()
        expect(store.values.contextItems).toEqual([])

        await expectLogic(logic, () => {
            logic.actions.handleTaxonomicFilterChange('7', TaxonomicFilterGroupType.Dashboards, {
                id: 7,
                name: 'Growth',
            })
        }).toFinishAllListeners()
        logic.unmount()
        expect(store.values.providers[PICKER_PROVIDER_ID]).toBeUndefined()
        expect(store.values.contextItems).toEqual([])
    })

    it('re-picking a dismissed item restores it', async () => {
        store.actions.registerContext('bridge', [{ type: 'insight', key: 'abc123', label: 'DAU' }])
        store.actions.dismissContext('insight:abc123')
        expect(store.values.contextItems).toEqual([])

        await expectLogic(logic, () => {
            logic.actions.handleTaxonomicFilterChange('abc123', TaxonomicFilterGroupType.Insights, {
                short_id: 'abc123',
                name: 'DAU',
            })
        }).toFinishAllListeners()
        expect(store.values.contextItems).toEqual([{ type: 'insight', key: 'abc123', label: 'DAU' }])
    })
})
