import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { WorkflowSavedViewActions } from './WorkflowSavedViewActions'
import { BUILT_IN_WORKFLOW_VIEWS, SavedViewAction } from './workflowSavedViews'

describe('saved workflow view actions', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each<[SavedViewAction, string]>([
        ['reset', 'workflows-combined-reset-view'],
        ['update', 'workflows-combined-update-view'],
        ['save-as', 'workflows-combined-save-as-new'],
    ])('spins only the button that started a pending %s', (pendingAction, startedBy) => {
        const { container } = render(
            <WorkflowSavedViewActions
                activeView={{ ...BUILT_IN_WORKFLOW_VIEWS[1], id: 'shared', name: 'Active flows', builtIn: false }}
                isModified
                hasAddedFilters={false}
                activeViewConflicted={false}
                canUpdateActiveView
                activeViewChanges={['filters']}
                pendingAction={pendingAction}
                onReset={jest.fn()}
                onSaveAs={jest.fn()}
                onSave={jest.fn()}
                onRename={jest.fn()}
                onDelete={jest.fn()}
            />
        )
        const spinning = [...container.querySelectorAll('.LemonButton--loading')].map((button) =>
            button.getAttribute('data-attr')
        )
        expect(spinning).toEqual([startedBy])
    })

    it('offers reset on an unchanged view that a teammate changed, so a failed rename or delete can be retried', async () => {
        const onReset = jest.fn()
        render(
            <WorkflowSavedViewActions
                activeView={{ ...BUILT_IN_WORKFLOW_VIEWS[1], id: 'shared', name: 'Active flows', builtIn: false }}
                isModified={false}
                hasAddedFilters={false}
                activeViewConflicted
                canUpdateActiveView
                activeViewChanges={[]}
                pendingAction={null}
                onReset={onReset}
                onSaveAs={jest.fn()}
                onSave={jest.fn()}
                onRename={jest.fn()}
                onDelete={jest.fn()}
            />
        )
        await userEvent.click(screen.getByLabelText('Load the latest version of Active flows'))
        expect(onReset).toHaveBeenCalledTimes(1)
    })
})
