import { initKeaTests } from '~/test/init'

import { pendingFingerprintIssueStateUpdateLogic } from '../../logics/pendingFingerprintIssueStateUpdateLogic'
import { issueActionsLogic } from './issueActionsLogic'

describe('issueActionsLogic', () => {
    let logic: ReturnType<typeof issueActionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = issueActionsLogic()
        logic.mount()
    })

    afterEach(() => logic?.unmount())

    it('mounts the pending-update store so detail-view mutations are recorded', () => {
        // The detail view connects issueActionsLogic but not the list scene, so before this the
        // store was unmounted and a resolve there captured nothing — the list still showed active.
        expect(pendingFingerprintIssueStateUpdateLogic.isMounted()).toBe(true)
    })
})
