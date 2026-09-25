import { urls } from 'scenes/urls'

import { inboxReportDetailUrl, inboxTabRedirectPath } from './inboxReportUrls'

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

        it('addresses the report through its legacy tab when asked', () => {
            expect(inboxReportDetailUrl('r1', undefined, 'pulls')).toBe(urls.inboxReport('pulls', 'r1'))
        })
    })

    // Slack notifications and bookmarks carry whichever tab segments were live when they were
    // written, and the flag can flip between visits, so each layout redirects the other's segments.
    describe('inboxTabRedirectPath', () => {
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
            ['settings', null],
            ['0198a1b2-report-id', null],
            [undefined, null],
        ])('under the redesign maps %s', (tab, path) => {
            expect(inboxTabRedirectPath(tab, true)).toBe(path)
        })

        it.each<[string | undefined, string | null]>([
            ['settings', urls.inbox('config')],
            ['pulls', null],
            ['config', null],
            ['runs', null],
            ['reports', null],
            ['0198a1b2-report-id', null],
            [undefined, null],
        ])('with the flag off maps %s', (tab, path) => {
            expect(inboxTabRedirectPath(tab, false)).toBe(path)
        })
    })
})
