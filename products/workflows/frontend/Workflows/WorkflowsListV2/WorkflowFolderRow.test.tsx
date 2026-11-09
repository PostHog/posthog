import { MOCK_TEAM_ID } from 'lib/api.mock'

import { DragStartEvent, useDndMonitor } from '@dnd-kit/core'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { Link } from 'lib/lemon-ui/Link'

import { ProjectDragAndDropProvider } from '~/layout/panel-layout/ProjectTree/ProjectDragAndDropContext'
import { initKeaTests } from '~/test/init'

import { WORKFLOW_FILES_DRAG_SCOPE } from './workflowFolderDragScopes'
import { WorkflowFolderRow } from './WorkflowFolderRow'

describe('WorkflowFolderRow', () => {
    let started: string[]

    function DragProbe(): null {
        useDndMonitor({ onDragStart: ({ active }: DragStartEvent) => started.push(String(active.id)) })
        return null
    }

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        started = []
        router.actions.push('/workflows')
        render(
            <ProjectDragAndDropProvider>
                <DragProbe />
                <WorkflowFolderRow icon={<span />} drag={{ id: 'project/welcome', label: 'Drag workflow Welcome' }}>
                    <Link to="/workflows/welcome">Welcome</Link>
                </WorkflowFolderRow>
            </ProjectDragAndDropProvider>
        )
    })

    afterEach(() => {
        act(() => jest.runOnlyPendingTimers())
        jest.useRealTimers()
        cleanup()
    })

    const pressNameAndMove = (distance: number): { followsLink: boolean } => {
        const name = screen.getByText('Welcome')
        fireEvent.mouseDown(name, { button: 0, clientX: 100, clientY: 100 })
        fireEvent.mouseMove(document, { clientX: 100 + distance, clientY: 100 })
        fireEvent.mouseUp(document, { clientX: 100 + distance, clientY: 100 })
        return { followsLink: fireEvent.click(name) }
    }

    it('starts the same drag from the name as from the handle, and stays put when dropped on the link', () => {
        expect(pressNameAndMove(40)).toEqual({ followsLink: false })
        expect(started).toEqual([`${WORKFLOW_FILES_DRAG_SCOPE}::project/welcome`])
        expect(router.values.location.pathname).toEqual(`/project/${MOCK_TEAM_ID}/workflows`)
    })

    it('opens the workflow on a click that moves less than the drag threshold', () => {
        pressNameAndMove(4)
        expect(started).toEqual([])
        expect(router.values.location.pathname).toEqual(`/project/${MOCK_TEAM_ID}/workflows/welcome`)
    })
})
