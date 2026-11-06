import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EventsRetentionLevel, eventsRetentionDeletionCountLogic } from './eventsRetentionDeletionCountLogic'

const TIMED_OUT_MONTHS = 1

describe('eventsRetentionDeletionCountLogic', () => {
    beforeEach(() => {
        const count =
            (perMonth: number) =>
            ({ request }: { request: Request }): [number, object] => {
                const months = Number(new URL(request.url).searchParams.get('retention_months'))
                if (months === TIMED_OUT_MONTHS) {
                    return [504, { detail: 'Query has hit the max execution time before completing.' }]
                }
                return [200, { retention_months: months, events_deleted: months * perMonth }]
            }
        useMocks({
            get: {
                '/api/projects/:team_id/events_retention/deletion_count/': count(100),
                '/api/organizations/:organization_id/events_retention_setting/deletion_count/': count(1000),
            },
        })
        initKeaTests()
    })

    it.each([
        ['project', 12, 1200],
        ['organization', 12, 12000],
        ['project', TIMED_OUT_MONTHS, null],
        ['organization', TIMED_OUT_MONTHS, null],
    ] as [EventsRetentionLevel, number, number | null][])(
        'counts the %s events %i months deletes',
        async (level, months, eventsDeleted) => {
            const logic = eventsRetentionDeletionCountLogic({ level, months })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values).toMatchObject({ eventsDeleted, eventsDeletedLoading: false })
        }
    )
})
