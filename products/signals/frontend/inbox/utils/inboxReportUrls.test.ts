import { urls } from 'scenes/urls'

import { inboxReportBackLabel, inboxReportDetailUrl, inboxTabRedirectPath } from './inboxReportUrls'

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

    describe('inboxReportBackLabel', () => {
        it.each<[string, string]>([
            [urls.inboxTriage(), 'Triage'],
            [`${urls.inboxTriage()}?report=r1&at=2`, 'Triage'],
            [urls.inbox('monitoring'), 'Monitoring'],
            [urls.inbox('scouts'), 'Scouts'],
            [urls.inboxScout('signals-scout-error-tracking'), 'Scout'],
            [`${urls.inboxScout('signals-scout-error-tracking', 'finding-1')}?tab=runs`, 'Scout'],
            [urls.inboxFindings(), 'Findings'],
            [urls.inboxRuns(), 'Runs'],
            [urls.inboxScratchpad(), 'Scratchpad'],
            ['/customers', 'Back'],
        ])('labels %s as %s', (backUrl, label) => {
            expect(inboxReportBackLabel(backUrl)).toBe(label)
        })
    })

    // Slack notifications and bookmarks carry whichever tab segments were live when they were
    // written, so old-layout segments redirect to the surface that replaced them.
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
            ['sources', null],
            ['settings', null],
            ['0198a1b2-report-id', null],
            [undefined, null],
        ])('maps %s', (tab, path) => {
            expect(inboxTabRedirectPath(tab)).toBe(path)
        })
    })
})
