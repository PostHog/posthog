import { urls } from 'scenes/urls'

import {
    inboxReportBackPath,
    inboxReportDetailUrl,
    inboxReportReturnPath,
    inboxTabRedirectPath,
} from './inboxReportUrls'

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

    // The back path decides where the report's back button and its verdict actions leave to. It is
    // read from a URL param that reaches the app from anywhere, so a non-internal value is rejected
    // to keep it from becoming an open redirect.
    describe('inboxReportBackPath', () => {
        it.each<[string, any, string | null]>([
            ['an internal path', '/inbox/scouts/signals-scout-general', '/inbox/scouts/signals-scout-general'],
            ['no back param', undefined, null],
            ['an absolute url', 'https://evil.test/phish', null],
            ['a protocol-relative url', '//evil.test/phish', null],
            ['a non-string value', 42, null],
        ])('honors %s', (_label, back, expected) => {
            expect(inboxReportBackPath({ back })).toBe(expected)
        })
    })

    describe('inboxReportReturnPath', () => {
        it('returns to the surface a report was opened from', () => {
            expect(inboxReportReturnPath({ back: '/inbox/scouts/signals-scout-general' }, 'reports')).toBe(
                '/inbox/scouts/signals-scout-general'
            )
        })

        it('falls back to the active list tab for a report opened straight off a list', () => {
            expect(inboxReportReturnPath({}, 'reports')).toBe(urls.inbox('reports'))
        })

        it('ignores a non-internal back path and falls back to the list', () => {
            expect(inboxReportReturnPath({ back: 'https://evil.test' }, 'reports')).toBe(urls.inbox('reports'))
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
