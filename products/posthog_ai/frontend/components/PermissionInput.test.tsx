import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import type { PermissionRequestRecord } from '../types/streamTypes'
import { PermissionInput } from './PermissionInput'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useActions: jest.fn(), useValues: jest.fn() }))
jest.mock('../logics/runStreamLogic', () => ({ runStreamLogic: jest.fn(() => ({})) }))
jest.mock('./tool/toolRegistry', () => ({ lookupToolRenderer: () => ({}) }))

describe('PermissionInput', () => {
    const respondToPermission = jest.fn()
    const cancelRun = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()
        localStorage.clear()
        ;(useActions as jest.Mock).mockReturnValue({ respondToPermission, cancelRun })
        ;(useValues as jest.Mock).mockReturnValue({ respondingToPermission: false })
    })

    afterEach(cleanup)

    it.each(['Bash', 'ExitPlanMode'])(
        'preserves %s feedback through hidden delivery and disables its shortcuts',
        (toolName) => {
            const request: PermissionRequestRecord = {
                requestId: 'approval-1',
                sourceRunId: 'run-1',
                toolCallId: 'tool-1',
                toolName,
                options: [
                    { optionId: 'auto', name: 'Allow', kind: 'allow_once' },
                    { optionId: 'reject', name: 'Do it differently', kind: 'reject_with_feedback' },
                ],
                rawToolCall: {
                    toolCallId: 'tool-1',
                    rawServerName: 'claude',
                    rawToolName: toolName,
                    input: {},
                    status: 'pending',
                    contentBlocks: [],
                },
            }
            const { rerender } = render(<PermissionInput streamKey="run-1" request={request} />)
            fireEvent.keyDown(document.body, { key: '2' })
            const input = screen.getByPlaceholderText(/tell the agent what to do differently/i)
            fireEvent.change(input, { target: { value: 'Use the example environment' } })
            fireEvent.keyDown(input, { key: 'Enter' })
            expect(respondToPermission).toHaveBeenCalledTimes(1)

            ;(useValues as jest.Mock).mockReturnValue({ respondingToPermission: true })
            rerender(<PermissionInput streamKey="run-1" request={request} />)
            for (const key of ['Escape', 'Tab', 'ArrowUp', '1', 'Enter']) {
                fireEvent.keyDown(document.body, { key })
            }
            expect(respondToPermission).toHaveBeenCalledTimes(1)
            expect(cancelRun).not.toHaveBeenCalled()

            ;(useValues as jest.Mock).mockReturnValue({ respondingToPermission: false })
            rerender(<PermissionInput streamKey="run-1" request={request} />)
            expect(screen.getByPlaceholderText(/tell the agent what to do differently/i)).toBe(input)
            expect(input).toHaveValue('Use the example environment')
            fireEvent.keyDown(input, { key: 'Enter' })
            expect(respondToPermission).toHaveBeenCalledTimes(2)
            expect(respondToPermission.mock.calls[1]).toEqual(respondToPermission.mock.calls[0])

            rerender(<PermissionInput streamKey="run-1" request={request} disabled />)
            fireEvent.keyDown(input, { key: 'Enter' })
            expect(respondToPermission).toHaveBeenCalledTimes(2)
        }
    )
})
