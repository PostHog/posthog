import { expectLogic } from 'kea-test-utils'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { attachedContextLogic } from '~/layout/ai/attachedContextLogic'
import { initKeaTests } from '~/test/init'

import { chatContextLogic, chatSendItems } from './chatContextLogic'
import { contextPickerLogic, taxonomicItemToAttachedContext } from './contextPickerLogic'

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
        // Events must key on the name, not the EventDefinition UUID (`item.id`) — tools resolve by name.
        [TaxonomicFilterGroupType.Events, { id: 'ev-uuid', name: '$pageview' }, 'event', '$pageview', '$pageview'],
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

    // A pick that missed the new chat's chips or its send would vanish without any error, and a dismissal must not block it.
    it('shows and sends a new chat pick, even of an item the user dismissed, until the chip is closed', async () => {
        store.actions.registerContext('bridge', [{ type: 'insight', key: 'abc123', label: 'DAU' }])
        store.actions.dismissContext('insight:abc123')
        const chat = chatContextLogic({})
        chat.mount()

        await expectLogic(logic, () => {
            logic.actions.handleTaxonomicFilterChange('abc123', TaxonomicFilterGroupType.Insights, {
                short_id: 'abc123',
                name: 'DAU',
            })
        }).toFinishAllListeners()

        expect(chat.values.chips.map((chip) => chip.id)).toEqual(['insight:abc123'])
        expect(chatSendItems(chat.values.pageItems, chat.values.picks)).toEqual([
            { type: 'insight', key: 'abc123', label: 'DAU' },
        ])

        chat.actions.removeChip(chat.values.chips[0])

        expect(chat.values.chips).toEqual([])
        chat.unmount()
    })

    // Closing a chip that is both a pick and on the page must hide it, or it would stay in the composer.
    it('removes a chip that is both picked and on the current page', () => {
        const item = { type: 'dashboard', key: 7, label: 'Growth' }
        store.actions.registerContext('bridge', [item])
        store.actions.pickItem(item)
        const chat = chatContextLogic({})
        chat.mount()
        expect(chat.values.chips).toHaveLength(1)

        chat.actions.removeChip(chat.values.chips[0])

        expect(chat.values.chips).toEqual([])
        chat.unmount()
    })

    // Removing a chip must stop its hidden payload, or a closed worksheet keeps sending its draft on every follow-up.
    it('stops sending a removed chip group in that started chat only, and across a re-registration', () => {
        const dismissGroup = 'bi-worksheet:abc'
        const worksheet = { type: 'insight', key: 'abc', label: 'Saved worksheet', dismissGroup }
        const metric = { type: 'data_catalog_metric', key: 'mrr', label: 'mrr', dismissGroup }
        const draft = { type: 'text', hidden: true, dismissGroup, value: 'worksheet draft' }
        store.actions.registerContext('bi', [worksheet, metric, draft])
        store.actions.contextDelivered('task-a', [worksheet, metric, draft])
        store.actions.contextDelivered('task-b', [worksheet, metric, draft])
        const chatA = chatContextLogic({ taskId: 'task-a' })
        const chatB = chatContextLogic({ taskId: 'task-b' })
        chatA.mount()
        chatB.mount()
        expect(chatA.values.pageItems).toEqual([draft])

        chatA.actions.removeChip(chatA.values.chips[0])
        store.actions.registerContext('bi', [worksheet, metric, { ...draft, value: 'edited draft' }])

        expect(chatA.values.chips).toEqual([])
        expect(chatA.values.pageItems).toEqual([])
        expect(chatB.values.pageItems.map((item) => item.value)).toEqual(['edited draft'])
        expect(chatB.values.chips).toHaveLength(2)
        chatA.unmount()
        chatB.unmount()
    })

    it('clears a new chat draft only when the new chat delivers it, not when another chat does', () => {
        const pick = { type: 'dashboard', key: 7, label: 'Growth' }
        store.actions.pickItem(pick)

        store.actions.contextDelivered('another-task', [pick])
        expect(store.values.pickedByChat['']).toEqual([pick])

        store.actions.contextDelivered('created-task', [pick], true)
        expect(store.values.pickedByChat['']).toEqual([])
    })
})
