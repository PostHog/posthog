import { urls } from 'scenes/urls'

import { inboxReportDetailUrl, inboxTabRedirectPath, resolveInboxTabAlias } from './inboxReportUrls'

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
    // written, so the redesign redirects the segments it replaced.
    describe('inboxTabRedirectPath', () => {
        it.each<[string | undefined, string | null]>([
            // The three old report lists are sections of one list now, so they all land on it.
            ['pulls', urls.inbox('reports')],
            ['archived', urls.inbox('reports')],
            ['not-actionable', urls.inbox('reports')],
            ['runs', urls.inboxRuns()],
            // The settings pair is resolved as an alias instead, so neither segment redirects.
            ['config', null],
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
            ['settings', null],
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

    // Both settings segments stay live under both layouts. Neither redirects, so the flag settling
    // mid-load cannot bounce the user between `/inbox/config` and `/inbox/settings`.
    describe('resolveInboxTabAlias', () => {
        it.each<[string | undefined, boolean, string | undefined]>([
            ['config', true, 'settings'],
            ['settings', true, 'settings'],
            ['settings', false, 'config'],
            ['config', false, 'config'],
            ['reports', true, 'reports'],
            ['pulls', false, 'pulls'],
            ['0198a1b2-report-id', true, '0198a1b2-report-id'],
            [undefined, true, undefined],
        ])('maps %s for redesign=%p to %s', (tab, redesign, expected) => {
            expect(resolveInboxTabAlias(tab, redesign)).toBe(expected)
        })
    })
})
