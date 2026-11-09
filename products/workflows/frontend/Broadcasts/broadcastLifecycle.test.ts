import '@testing-library/jest-dom'

import { fireEvent, screen, waitFor } from '@testing-library/react'

import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { archiveDisabledReason, confirmCreateAsBroadcast, summaryActions } from './broadcastLifecycle'

const TITLE = 'Track this send as a broadcast?'

describe('broadcastLifecycle', () => {
    describe('archiveDisabledReason', () => {
        it.each([
            { runs: 'runs not loaded yet', statuses: null, blocked: true },
            { runs: 'no runs', statuses: [], blocked: false },
            { runs: 'a finished and a failed run', statuses: ['completed', 'failed'], blocked: false },
            { runs: 'rows whose runs have not loaded', statuses: [undefined], blocked: false },
            { runs: 'a queued run', statuses: ['queued'], blocked: true },
            { runs: 'an older run still sending', statuses: ['completed', 'active'], blocked: true },
        ])('with $runs blocks archiving: $blocked', ({ statuses, blocked }) => {
            expect(!!archiveDisabledReason(statuses)).toBe(blocked)
        })
    })

    describe('summaryActions', () => {
        const priorAppContext = window.POSTHOG_APP_CONTEXT

        afterEach(() => {
            window.POSTHOG_APP_CONTEXT = priorAppContext
        })

        const disabledByLabel = (
            workflowAccess: AccessControlLevel,
            broadcastAccess: AccessControlLevel,
            isArchived: boolean
        ): Record<string, boolean> => {
            window.POSTHOG_APP_CONTEXT = {
                ...priorAppContext,
                resource_access_control: {
                    ...priorAppContext?.resource_access_control,
                    [AccessControlResourceType.Workflow]: workflowAccess,
                },
            } as AppContext
            const noop = (): void => {}
            const actions = summaryActions({
                userAccessLevel: broadcastAccess,
                canMoveToDraft: !isArchived,
                canEditContent: true,
                isArchived,
                batchJobStatuses: [],
                onMoveToDraft: noop,
                onSendAgain: noop,
                onRestore: noop,
                onArchive: noop,
                onDelete: noop,
            })
            return Object.fromEntries(actions.map((action) => [action.label, !!action.disabledReason]))
        }

        it.each([
            {
                grants: 'workflows viewer, broadcast editor',
                workflowAccess: AccessControlLevel.Viewer,
                broadcastAccess: AccessControlLevel.Editor,
                isArchived: false,
                disabled: { 'Stop and edit': false, 'Send again as a new broadcast': true, Archive: false },
            },
            {
                grants: 'workflows editor, broadcast viewer',
                workflowAccess: AccessControlLevel.Editor,
                broadcastAccess: AccessControlLevel.Viewer,
                isArchived: false,
                disabled: { 'Stop and edit': true, 'Send again as a new broadcast': false, Archive: true },
            },
            {
                grants: 'workflows editor, archived broadcast viewer',
                workflowAccess: AccessControlLevel.Editor,
                broadcastAccess: AccessControlLevel.Viewer,
                isArchived: true,
                disabled: { 'Send again as a new broadcast': false, 'Restore as draft': true, Delete: true },
            },
        ])(
            'with $grants checks Send again against workflows and the rest against the broadcast',
            ({ workflowAccess, broadcastAccess, isArchived, disabled }) => {
                expect(disabledByLabel(workflowAccess, broadcastAccess, isArchived)).toEqual(disabled)
            }
        )
    })

    describe('confirmCreateAsBroadcast', () => {
        const escape = (): boolean =>
            fireEvent.keyDown(screen.getByText(TITLE).closest('.ReactModal__Content')!, { key: 'Escape', keyCode: 27 })

        const others = [
            { id: 'wf-a', name: 'September newsletter', status: 'draft' as const },
            { id: 'wf-b', name: '', status: 'active' as const },
        ]

        it.each([
            { offered: [], button: 'Create broadcast', choice: 'broadcast' },
            { offered: [], button: 'Keep as workflow', choice: 'workflow' },
            { offered: [], button: null, choice: null },
            { offered: others, button: 'Create and move 2 more', choice: 'broadcast_and_move' },
            { offered: others, button: 'Create broadcast', choice: 'broadcast' },
            { offered: others, button: 'Keep as workflow', choice: 'workflow' },
        ])('with $offered.length other workflows, $button resolves to $choice', async ({ offered, button, choice }) => {
            const result = confirmCreateAsBroadcast(offered)
            await screen.findByText(TITLE)
            for (const name of offered.length
                ? ['Also move these 2 workflows to broadcasts?', 'September newsletter', 'Untitled workflow']
                : []) {
                expect(screen.getByText(name)).toBeInTheDocument()
            }

            if (button) {
                fireEvent.click(screen.getByText(button))
            } else {
                escape()
            }

            await expect(result).resolves.toBe(choice)
            await waitFor(() => expect(screen.queryByText(TITLE)).not.toBeInTheDocument())
        })
    })
})
