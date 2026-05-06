import { ProductKey } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import { buildAffectedUsersQuery, buildCrashFreeSessionsQuery, buildExceptionVolumeQuery } from './queries'

describe('error tracking insights queries', () => {
    it('tags chart queries as error tracking', () => {
        const filters = {
            filterGroup: {
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.And, values: [] }],
            },
            filterTestAccounts: false,
        }

        expect(buildExceptionVolumeQuery('-7d', null, filters).source.tags).toEqual({
            productKey: ProductKey.ERROR_TRACKING,
        })
        expect(buildAffectedUsersQuery('-7d', null, filters).source.tags).toEqual({
            productKey: ProductKey.ERROR_TRACKING,
        })
        expect(buildCrashFreeSessionsQuery('-7d', null, filters).source.tags).toEqual({
            productKey: ProductKey.ERROR_TRACKING,
        })
    })
})
