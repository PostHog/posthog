/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inboxFiltersLogic } from '../logics/inboxFiltersLogic'
import { reportListLogic, sectionListLogicProps } from '../logics/reportListLogic'
import { INBOX_REPORT_SECTION_KEYS, INBOX_SCOPE_ENTIRE_PROJECT, SignalReport, SignalReportStatus } from '../types'
import { inboxReportQueue, reportQueuePosition } from './reportQueue'

function makeReport(id: string, isSuggestedReviewer = false): SignalReport {
    return {
        id,
        title: `Report ${id}`,
        summary: 'summary',
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        artefact_count: 0,
        is_suggested_reviewer: isSuggestedReviewer,
        priority: 'P2',
        source_products: ['error_tracking'],
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
    } satisfies SignalReport
}

describe('reportQueuePosition', () => {
    test.each([
        ['the first report', 'a', { position: 1, total: 54, previousId: null, nextId: 'b' }],
        ['a middle report', 'b', { position: 2, total: 54, previousId: 'a', nextId: 'c' }],
        ['the last loaded report', 'c', { position: 3, total: 54, previousId: 'b', nextId: null }],
        ['a report that the list does not hold', 'z', null],
    ])('%s', (_name, id, expected) => {
        expect(reportQueuePosition(['a', 'b', 'c'], 54, id)).toEqual(expected)
    })

    it('never counts fewer reports than the list holds', () => {
        expect(reportQueuePosition(['a', 'b', 'c'], 0, 'c')?.total).toBe(3)
    })

    test.each([
        ['leads with the For you group in the Quill list', true, { position: 2, previousId: 'b', nextId: 'c' }],
        ['keeps the merged order in the legacy list', false, { position: 1, previousId: null, nextId: 'b' }],
    ])('%s', async (_name, todayRailNav, expected) => {
        const reports = [makeReport('a'), makeReport('b', true), makeReport('c')]
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                '/api/projects/:team_id/signals/reports/': { count: reports.length, next: null, results: reports },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TODAY_RAIL_NAV]: todayRailNav })
        inboxFiltersLogic.mount()
        inboxFiltersLogic.actions.setScope(INBOX_SCOPE_ENTIRE_PROJECT)
        const lists = INBOX_REPORT_SECTION_KEYS.map((sectionKey) => reportListLogic(sectionListLogicProps(sectionKey)))
        lists.forEach((list) => {
            list.mount()
            list.actions.ensureLoaded()
        })
        await waitFor(() => expect(lists.every((list) => list.values.isLoaded)).toBe(true))

        expect(inboxReportQueue('a')).toMatchObject(expected)
    })
})
