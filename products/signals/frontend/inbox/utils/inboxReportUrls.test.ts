import { urls } from 'scenes/urls'

import { inboxReportDetailUrl, legacyInboxTabPath } from './inboxReportUrls'

describe('inbox report urls', () => {
    describe('inboxReportDetailUrl', () => {
        it('links straight to the report from inside the inbox', () => {
            expect(inboxReportDetailUrl('r1')).toBe(urls.inboxReport('reports', 'r1'))
        })

        it('carries the return path for a card embedded outside the inbox', () => {
            expect(inboxReportDetailUrl('r1', '/customers')).toBe(
                `${urls.inboxReport('reports', 'r1')}?back=%2Fcustomers`
            )
        })
    })

    // Slack notifications and bookmarks still carry the pre-redesign tab segments.
    describe('legacyInboxTabPath', () => {
        it.each<[string | undefined, string | null]>([
            // The three old report lists are sections of one list now, so they all land on it.
            ['pulls', urls.inbox('reports')],
            ['archived', urls.inbox('reports')],
            ['not-actionable', urls.inbox('reports')],
            ['runs', urls.inboxRuns()],
            ['config', urls.inbox('settings')],
            // Live segments and bare report ids are left for their own route handlers.
            ['reports', null],
            ['scouts', null],
            ['0198a1b2-report-id', null],
            [undefined, null],
        ])('maps %s', (tab, path) => {
            expect(legacyInboxTabPath(tab)).toBe(path)
        })
    })
})
