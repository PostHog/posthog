import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { workflowSceneLogic } from './workflowSceneLogic'

describe('workflowSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    // Guards the side panel wiring: the access control (and activity) tab only appears when the scene logic
    // — the one sidePanelContextLogic reads SIDE_PANEL_CONTEXT_KEY from — exposes the hog_flow resource.
    it('exposes the hog_flow access control context for a saved workflow', () => {
        const logic = workflowSceneLogic({ id: '0190abcd-1234-7000-8000-000000000000' })
        logic.mount()

        expect(logic.values.sidePanelContext).toEqual({
            activity_scope: ActivityScope.HOG_FLOW,
            activity_item_id: '0190abcd-1234-7000-8000-000000000000',
            access_control_resource: 'hog_flow',
            access_control_resource_id: '0190abcd-1234-7000-8000-000000000000',
        })
    })

    it('exposes no access control context for an unsaved workflow', () => {
        const logic = workflowSceneLogic({ id: 'new' })
        logic.mount()

        expect(logic.values.sidePanelContext).toBeNull()
    })
})
