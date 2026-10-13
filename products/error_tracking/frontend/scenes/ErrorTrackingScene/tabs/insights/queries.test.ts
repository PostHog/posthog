import { ProductKey } from '~/queries/schema/schema-general'
import { HogQLMathType } from '~/types'

import {
    buildAffectedUsersQuery,
    buildCrashFreeSessionsQuery,
    buildExceptionVolumeQuery,
    buildIssuesCreatedQuery,
} from './queries'

describe('error tracking insights queries', () => {
    it('tags chart queries as error tracking', () => {
        const filters = {
            properties: [],
            filterTestAccounts: false,
        }
        const dateRange = { date_from: '-7d', date_to: null }

        expect(buildExceptionVolumeQuery(dateRange, filters).source.tags).toEqual({
            productKey: ProductKey.ERROR_TRACKING,
        })
        expect(buildIssuesCreatedQuery(dateRange, filters).source.tags).toEqual({
            productKey: ProductKey.ERROR_TRACKING,
        })
        expect(buildAffectedUsersQuery(dateRange, filters).source.tags).toEqual({
            productKey: ProductKey.ERROR_TRACKING,
        })
        expect(buildCrashFreeSessionsQuery(dateRange, filters).source.tags).toEqual({
            productKey: ProductKey.ERROR_TRACKING,
        })
    })

    it('counts each issue on its first exception', () => {
        const query = buildIssuesCreatedQuery(
            { date_from: '-7d', date_to: null },
            { properties: [], filterTestAccounts: false }
        )

        expect(query.source.series[0]).toMatchObject({
            event: '$exception',
            custom_name: 'Issues created',
            math: HogQLMathType.HogQL,
            math_hogql: 'uniqIf(issue_id, timestamp = issue_first_seen)',
        })
    })
})
