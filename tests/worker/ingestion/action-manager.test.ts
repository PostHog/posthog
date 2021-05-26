import { Hub, PropertyOperator, RawAction } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { ActionManager } from '../../../src/worker/ingestion/action-manager'
import { resetTestDatabase } from '../../helpers/sql'

describe('ActionManager', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let actionManager: ActionManager

    beforeEach(async () => {
        ;[hub, closeServer] = await createHub()
        await resetTestDatabase()
        actionManager = new ActionManager(hub.db)
        await actionManager.prepare()
    })
    afterEach(async () => {
        await closeServer()
    })

    it('returns the correct action', async () => {
        const ACTION_ID = 69
        const ACTION_STEP_ID = 913

        const action = actionManager.getAction(ACTION_ID)

        expect(action).toMatchObject({
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
                    properties: [{ type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] }],
                },
            ],
        })

        await hub.db.postgresQuery(
            `UPDATE posthog_actionstep SET properties = jsonb_set(properties, '{0,key}', '"baz"') WHERE id = $1`,
            [ACTION_STEP_ID],
            'testKey'
        )

        // This is normally dispatched by Django and broadcasted by Piscina
        await actionManager.reloadAction(ACTION_ID)

        const reloadedAction = actionManager.getAction(ACTION_ID)

        expect(reloadedAction).toMatchObject({
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
                    properties: [{ type: 'event', operator: PropertyOperator.Exact, key: 'baz', value: ['bar'] }],
                },
            ],
        })

        // This is normally dispatched by Django and broadcasted by Piscina
        actionManager.dropAction(ACTION_ID)

        const droppedAction = actionManager.getAction(ACTION_ID)

        expect(droppedAction).toBeUndefined()
    })
})
