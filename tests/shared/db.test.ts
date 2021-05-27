import { Hub, PropertyOperator } from '../../src/types'
import { DB } from '../../src/utils/db/db'
import { createHub } from '../../src/utils/db/hub'
import { ActionManager } from '../../src/worker/ingestion/action-manager'
import { resetTestDatabase } from '../helpers/sql'

describe('DB', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let db: DB

    beforeEach(async () => {
        ;[hub, closeServer] = await createHub()
        await resetTestDatabase()
        db = hub.db
    })

    afterEach(async () => {
        await closeServer()
    })

    const TEAM_ID = 2
    const ACTION_ID = 69
    const ACTION_STEP_ID = 913

    test('fetchAllActionsGroupedByTeam', async () => {
        const action = await db.fetchAllActionsGroupedByTeam()

        expect(action).toMatchObject({
            [TEAM_ID]: {
                [ACTION_ID]: {
                    id: ACTION_ID,
                    name: 'Test Action',
                    deleted: false,
                    post_to_slack: false,
                    slack_message_format: '',
                    is_calculating: false,
                    steps: [
                        {
                            id: ACTION_STEP_ID,
                            action_id: ACTION_ID,
                            tag_name: null,
                            text: null,
                            href: null,
                            selector: null,
                            url: null,
                            url_matching: null,
                            name: null,
                            event: null,
                            properties: [
                                { type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] },
                            ],
                        },
                    ],
                },
            },
        })
    })
})
