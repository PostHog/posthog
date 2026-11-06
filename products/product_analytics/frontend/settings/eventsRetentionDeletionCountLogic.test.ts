import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    EventsRetentionDeletionCountKind,
    eventsRetentionDeletionCountLogic,
} from './eventsRetentionDeletionCountLogic'

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
                '/api/organizations/:organization_id/events_retention_setting/downgrade_deletion_count/': count(10),
            },
        })
        initKeaTests()
    })

    it.each([
        ['project', 12, 1200],
        ['organization', 12, 12000],
        ['downgrade', 12, 120],
        ['project', TIMED_OUT_MONTHS, null],
        ['organization', TIMED_OUT_MONTHS, null],
    ] as [EventsRetentionDeletionCountKind, number, number | null][])(
        'counts the %s events %i months deletes',
        async (count, months, eventsDeleted) => {
            const logic = eventsRetentionDeletionCountLogic({ count, months })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values).toMatchObject({ eventsDeleted, eventsDeletedLoading: false })
        }
    )
})
