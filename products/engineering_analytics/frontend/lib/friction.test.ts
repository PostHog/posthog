import type { PullRequestFrictionBreakdownApi } from '../generated/api.schemas'
import { pullRequestFrictionFacts } from './friction'

const QUIET: PullRequestFrictionBreakdownApi = {
    score: 0.2,
    groups: [],
    flake_red_count: 0,
    master_red_count: 0,
    unknown_red_count: 0,
    own_red_count: 0,
    futile_rerun_count: 0,
    push_count: 1,
    ci_wait_seconds: [],
    first_approval_wait_seconds: null,
    pushes_after_approval: null,
    queue_seconds: null,
    kickout_count: null,
}

describe('pullRequestFrictionFacts', () => {
    test.each([
        ['a pull request that met nothing lists nothing', QUIET, []],
        ['a pull request without CI pushes shows no negative extra pushes', { ...QUIET, push_count: 0 }, []],
        [
            'only what happened shows, in group order',
            { ...QUIET, master_red_count: 2, kickout_count: 1, push_count: 3, ci_wait_seconds: [600, 1200] },
            // pluralize joins the count and the noun with a non-breaking space.
            [
                ['queue', 'Kicked out of the merge queue', '1'],
                ['ci', 'Red, the default branch was failing', '2'],
                ['ci', 'CI running', '30m over 3\u00a0pushes'],
                ['rework', 'Extra pushes', '2'],
            ],
        ],
    ])('%s', (_name, pr, expected) => {
        expect(pullRequestFrictionFacts(pr).map((fact) => [fact.group, fact.label, fact.value])).toEqual(expected)
    })
})
