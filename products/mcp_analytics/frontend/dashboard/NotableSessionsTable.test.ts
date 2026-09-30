import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { sessionsUrl } from './NotableSessionsTable'

describe('sessionsUrl', () => {
    const sharedParams = {
        date_from: '-7d',
        has_errors: 'true',
    }

    it('links a notable session through the session search filter', () => {
        expect(sessionsUrl({ ...sharedParams, search: 'old-session' }, 'linked-session')).toBe(
            combineUrl(urls.mcpAnalyticsSessions(), { ...sharedParams, search: 'linked-session' }).url
        )
    })

    it('opens the full session list without stale search state', () => {
        expect(sessionsUrl({ ...sharedParams, search: 'old-session' })).toBe(
            combineUrl(urls.mcpAnalyticsSessions(), sharedParams).url
        )
    })
})
