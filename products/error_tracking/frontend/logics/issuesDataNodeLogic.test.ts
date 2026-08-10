import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ISSUES_DATA_NODE_KEY, issuesDataNodeLogic } from './issuesDataNodeLogic'

describe('issuesDataNodeLogic', () => {
    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/': { results: [] },
            },
        })
        initKeaTests()
    })

    // ReloadIssuesButton binds issuesDataNodeLogic with no props, so a mount outside the IssuesList
    // BindLogic must fall back to a defined key. Without the default it forwarded undefined to the
    // keyed dataNodeLogic and crashed React render with "Undefined key for logic".
    it('mounts without a BindLogic and keys its dataNodeLogic', () => {
        const logic = issuesDataNodeLogic()
        expect(logic.props.key).toEqual(ISSUES_DATA_NODE_KEY)
        expect(() => logic.mount()).not.toThrow()
    })
})
