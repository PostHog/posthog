import { ProductKey } from '~/queries/schema/schema-general'

import { buildAffectedUsersQuery, buildCrashFreeSessionsQuery, buildExceptionVolumeQuery } from './queries'

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
        expect(buildAffectedUsersQuery(dateRange, filters).source.tags).toEqual({
            productKey: ProductKey.ERROR_TRACKING,
        })
        expect(buildCrashFreeSessionsQuery(dateRange, filters).source.tags).toEqual({
            productKey: ProductKey.ERROR_TRACKING,
        })
    })
})
