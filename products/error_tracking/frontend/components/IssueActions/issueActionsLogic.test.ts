import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { issueActionsLogic } from './issueActionsLogic'

describe('issueActionsLogic', () => {
    let logic: ReturnType<typeof issueActionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = issueActionsLogic()
        logic.mount()
    })

    afterEach(() => logic?.unmount())

    // A large selection used to go out as one POST that row-locks every source issue and can time
    // out under the background auto-merge. It must now split into batches merged into the same primary.
    it('splits a large merge selection into batches merged into the same primary', async () => {
        const mergeInto = jest.spyOn(api.errorTracking, 'mergeInto').mockResolvedValue({ content: '' })

        const ids = Array.from({ length: 60 }, (_, index) => `issue-${index}`)
        await expectLogic(logic, () => {
            logic.actions.mergeIssues(ids)
        }).toDispatchActions(['mutationSuccess'])

        const primary = ids[0]
        const sources = ids.slice(1)
        expect(mergeInto.mock.calls.map((call) => call[0])).toEqual([primary, primary, primary])
        expect(mergeInto.mock.calls.flatMap((call) => call[1])).toEqual(sources)

        mergeInto.mockRestore()
    })
})
