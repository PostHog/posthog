import type { ErrorTrackingRecommendation } from '../recommendations/types'
import { findingsByLens } from './impactFindings'

const HOUR = '2026-10-14T09:00:00+00:00'
const EARLIER_HOUR = '2026-10-14T03:00:00+00:00'
const PAGES = ['app.example.com/projects', 'app.example.com/projects/:n', 'app.example.com/projects/:n/reports']

const lens = (
    type: ErrorTrackingRecommendation['type'],
    meta: Record<string, unknown>
): ErrorTrackingRecommendation => ({
    id: `${type}-id`,
    type,
    meta,
    completed: false,
    status: 'ready',
    computed_at: '2026-10-14T12:00:00Z',
    dismissed_at: null,
    created_at: '2026-10-14T12:00:00Z',
    updated_at: '2026-10-14T12:00:00Z',
})

const issue = { id: 'broken', name: 'TypeError', description: null, status: 'active' }

describe('findingsByLens', () => {
    // Each issue names the incident it came from, and the signal draws that incident, so the wrong one or none misleads.
    it.each([
        {
            type: 'flow_drop' as const,
            incident: (hour: string) => ({ from_path: PAGES[0], to_path: PAGES[1], hour }),
            located: { from_path: PAGES[0], to_path: PAGES[1] },
        },
        {
            type: 'funnel_step' as const,
            // A copy of the chain's pages, as each list arrives as its own array from the API.
            incident: (hour: string) => ({ pages: [...PAGES], hour }),
            located: { pages: [...PAGES] },
        },
    ])('pairs each $type issue with the incident of its pages and hour', ({ type, incident, located }) => {
        const findings = findingsByLens([
            lens(type, {
                incidents: [incident(EARLIER_HOUR), incident(HOUR)],
                issues: [{ ...issue, ...located, hour: HOUR }],
            }),
        ])

        expect(findings[type]?.map((finding) => ('incident' in finding ? finding.incident?.hour : null))).toEqual([
            HOUR,
        ])
    })
})
