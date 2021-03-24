import { DateTime } from 'luxon'
import { Pool } from 'pg'
import { mocked } from 'ts-jest/utils'

import { defaultConfig } from '../../../src/shared/config'
import { DB } from '../../../src/shared/db'
import { createServer } from '../../../src/shared/server'
import { UUIDT } from '../../../src/shared/utils'
import { PluginsServer } from '../../../src/types'
import { PersonManager } from '../../../src/worker/ingestion/person-manager'
import { resetTestDatabase } from '../../helpers/sql'

describe('PersonManager.isNewPerson', () => {
    let personManager: PersonManager
    let server: PluginsServer
    let closeServer: () => Promise<void>

    const check = (distinctId: string) => personManager.isNewPerson(server.db, 2, distinctId)
    const createPerson = async (distinctId: string) => {
        const uuid = new UUIDT().toString()
        await server.db.createPerson(DateTime.utc(), {}, 2, null, false, uuid, [distinctId])
    }

    beforeEach(async () => {
        await resetTestDatabase()
        ;[server, closeServer] = await createServer({
            DISTINCT_ID_LRU_SIZE: 10,
        })
        personManager = new PersonManager(server)
    })

    afterEach(async () => {
        await closeServer()
    })

    it('returns whether person exists or not', async () => {
        await createPerson('1234')

        expect(await check('1234')).toEqual(false)
        expect(await check('12345')).toEqual(true)
        expect(await check('567')).toEqual(true)
        expect(await check('567')).toEqual(false)
    })

    it('keeps a cache', async () => {
        await createPerson('1234')
        await createPerson('567')

        const spy = jest.spyOn(server.db, 'postgresQuery')

        expect(await check('1234')).toEqual(false)
        expect(await check('567')).toEqual(false)
        expect(await check('1234')).toEqual(false)
        expect(await check('1234')).toEqual(false)
        expect(await check('1234')).toEqual(false)
        expect(await check('new-id')).toEqual(true)
        expect(await check('new-id')).toEqual(false)

        expect(spy).toHaveBeenCalledTimes(3)
    })
})
