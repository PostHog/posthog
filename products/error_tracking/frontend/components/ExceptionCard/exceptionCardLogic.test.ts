import { initKeaTests } from '~/test/init'

import { exceptionCardLogic } from './exceptionCardLogic'

describe('exceptionCardLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('keeps tab state separate for cards with different logic keys', () => {
        const issueCard = exceptionCardLogic({ issueId: 'issue-id', loading: false })
        const modalCard = exceptionCardLogic({
            issueId: 'issue-id',
            loading: false,
            logicKey: 'manage-fingerprints-issue-id',
        })
        const unmountIssueCard = issueCard.mount()
        const unmountModalCard = modalCard.mount()

        modalCard.actions.setCurrentTab('properties')

        expect(modalCard.values.currentTab).toBe('properties')
        expect(issueCard.values.currentTab).toBe('stack_trace')

        unmountModalCard()
        unmountIssueCard()
    })
})
