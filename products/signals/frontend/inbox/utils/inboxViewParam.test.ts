import { urls } from 'scenes/urls'

import { InboxFlatListTabKey } from '../types'
import {
    inboxReportDetailUrl,
    inboxViewSearchParams,
    legacyInboxTabPath,
    legacyInboxTabView,
    parseInboxViewParam,
} from './inboxViewParam'

describe('inbox view param', () => {
    describe('parseInboxViewParam', () => {
        it.each<[string, unknown, { is_staff?: boolean } | null, InboxFlatListTabKey]>([
            ['a known view', 'monitoring', { is_staff: false }, 'monitoring'],
            // A shared link with a typo (or an old value) lands on the default rather than a blank list.
            ['an unknown value', 'pulls', { is_staff: false }, 'needs-decision'],
            ['no value', undefined, { is_staff: false }, 'needs-decision'],
            // Staff-only views bounce non-staff users once the user has resolved.
            ['a staff-only view for a non-staff user', 'not-actionable', { is_staff: false }, 'needs-decision'],
            ['a staff-only view for a staff user', 'not-actionable', { is_staff: true }, 'not-actionable'],
            // Before the user resolves, keep the view so a staff member's deep link isn't misrouted.
            ['a staff-only view before the user resolves', 'not-actionable', null, 'not-actionable'],
        ])('resolves %s', (_label, raw, user, expected) => {
            expect(parseInboxViewParam(raw, user)).toBe(expected)
        })
    })

    describe('inboxViewSearchParams', () => {
        it('writes a non-default view and keeps the other params', () => {
            expect(inboxViewSearchParams({ scope: 'entire-project' }, 'resolved')).toEqual({
                scope: 'entire-project',
                view: 'resolved',
            })
        })

        it('drops the param for the landing view so the default URL stays clean', () => {
            expect(inboxViewSearchParams({ view: 'monitoring', search: 'x' }, 'needs-decision')).toEqual({
                search: 'x',
            })
        })
    })

    describe('inboxReportDetailUrl', () => {
        it.each<[string, InboxFlatListTabKey, string | undefined, string]>([
            ['the landing view', 'needs-decision', undefined, urls.inboxReport('reports', 'r1')],
            ['another view', 'monitoring', undefined, `${urls.inboxReport('reports', 'r1')}?view=monitoring`],
            [
                'an embedding surface',
                'resolved',
                '/customers',
                `${urls.inboxReport('reports', 'r1')}?back=%2Fcustomers&view=resolved`,
            ],
        ])('carries the view from %s', (_label, view, backUrl, expected) => {
            expect(inboxReportDetailUrl('r1', view, backUrl)).toBe(expected)
        })
    })

    // Slack notifications and bookmarks still carry the pre-redesign tab segments.
    describe('legacy tab segments', () => {
        it.each<[string | undefined, InboxFlatListTabKey | null, string | null]>([
            ['pulls', 'monitoring', null],
            ['archived', 'resolved', null],
            ['not-actionable', 'not-actionable', null],
            ['runs', null, urls.inboxRuns()],
            ['config', null, urls.inbox('settings')],
            ['reports', null, null],
            ['0198a1b2-report-id', null, null],
            [undefined, null, null],
        ])('maps %s', (tab, view, path) => {
            expect(legacyInboxTabView(tab)).toBe(view)
            expect(legacyInboxTabPath(tab)).toBe(path)
        })
    })
})
