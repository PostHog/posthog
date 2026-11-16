import { router } from 'kea-router'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import { initKeaTests } from '~/test/init'

import { workflowsSceneLogic } from './WorkflowsScene'

const WORKFLOW_ID = '0190f1a2-7c3b-7000-8000-000000000001'

describe('workflowsSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
        workflowsSceneLogic.mount()
    })

    it.each([
        ['a bare workflow id opens that workflow', `/workflows/${WORKFLOW_ID}`, `/workflows/${WORKFLOW_ID}/workflow`],
        ['a known tab stays on the list', '/workflows/templates', '/workflows/templates'],
        ['an unknown tab stays on the list', '/workflows/not-a-tab', '/workflows/not-a-tab'],
    ])('%s', (_, path, expectedPath) => {
        router.actions.push(path)

        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(expectedPath)
    })
})
