import {
    RoutingOwnerOutcomeEnumApi,
    type StamphogRoutingRunApi,
    type StamphogRoutingRunOwnerApi,
} from '../../generated/api.schemas'
import { AREA_FILTER_OUTCOMES, AreaGroup, areaGroup, groupAreaRows, isMergedWithoutTeam } from './areaDisplay'

const run = (size: number | null, decision: Partial<StamphogRoutingRunOwnerApi>, id = 'run'): StamphogRoutingRunApi =>
    ({
        id,
        pull_request: { additions: size, deletions: size === null ? null : 0 },
        owners: [{ owner: 'team-devex', outcome: 'not_requested', pins: [], lines: 50, ...decision }],
    }) as unknown as StamphogRoutingRunApi

describe('areaDisplay', () => {
    test.each<[string, StamphogRoutingRunApi, AreaGroup]>([
        [
            'a sensitive pin needs a look even when the team was asked',
            run(1000, { outcome: 'requested', pins: [{ reason: 'sensitive', path: '.github/workflows/ci.yml' }] }),
            'needs_a_look',
        ],
        ['half of the change merged without the team needs a look', run(100, { lines: 50 }), 'needs_a_look'],
        ['less than half merged without the team', run(101, { lines: 50 }), 'merged_without_team'],
        ['an unmerged size cannot need a look by share', run(null, { lines: 50 }), 'merged_without_team'],
        [
            'a request GitHub refused leaves the team unasked',
            run(100, { outcome: 'refused', lines: 90 }),
            'merged_without_team',
        ],
        ['a fork label counts as asked', run(100, { outcome: 'labeled' }), 'team_asked'],
        ['a cut is a small part', run(100, { outcome: 'cut', lines: 90 }), 'small_part'],
    ])('%s', (_name, areaRun, expected) => {
        expect(areaGroup({ run: areaRun, decision: areaRun.owners[0] })).toEqual(expected)
    })

    it("sorts a group by the team's lines and leaves out runs without the team", () => {
        const runs = [
            run(1000, { lines: 10 }, 'small'),
            run(1000, { lines: 300 }, 'large'),
            run(1000, { owner: 'team-infra' }, 'other team'),
        ]

        expect(
            groupAreaRows(runs, 'team-devex').map((group) => [group.key, group.rows.map((row) => row.run.id)])
        ).toEqual([['merged_without_team', ['large', 'small']]])
    })

    it('the merged without your team segment asks for every outcome the headline counts', () => {
        expect(new Set(AREA_FILTER_OUTCOMES.merged_without_team)).toEqual(
            new Set(Object.values(RoutingOwnerOutcomeEnumApi).filter(isMergedWithoutTeam))
        )
    })
})
