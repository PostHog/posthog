import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { lazy, type ComponentType } from 'react'

import type { PermissionPreviewProps } from '../api/tools'
import type { PermissionRequestRecord } from '../types/streamTypes'
import { PermissionInput } from './PermissionInput'
import { lookupToolRenderer } from './tool/toolRegistry'

jest.mock('kea', () => ({
    ...jest.requireActual<typeof import('kea')>('kea'),
    useActions: jest.fn(),
    useValues: jest.fn(),
}))
jest.mock('../logics/runStreamLogic', () => ({ runStreamLogic: jest.fn(() => ({})) }))
jest.mock('./tool/toolRegistry', () => ({ lookupToolRenderer: jest.fn(() => ({})) }))

describe('PermissionInput', () => {
    const respondToPermission = jest.fn()
    const cancelRun = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()
        jest.mocked(lookupToolRenderer).mockReturnValue({} as ReturnType<typeof lookupToolRenderer>)
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
    const previewRequest: PermissionRequestRecord = {
        requestId: 'preview-1',
        toolCallId: 'preview-tool-1',
        toolName: 'Bash',
        options: [
            { optionId: 'allow', name: 'Allow', kind: 'allow_once' },
            { optionId: 'reject', name: 'Decline', kind: 'reject_once' },
        ],
        rawToolCall: {
            toolCallId: 'preview-tool-1',
            rawServerName: 'claude',
            rawToolName: 'Bash',
            input: { command: 'echo synthetic-evidence' },
            status: 'pending',
            contentBlocks: [],
        },
    }

    it('keeps evidence and approval controls usable while a lazy preview loads', async () => {
        let resolvePreview!: (value: { default: ComponentType<PermissionPreviewProps> }) => void
        const PermissionPreview = lazy(
            () =>
                new Promise<{ default: ComponentType<PermissionPreviewProps> }>((resolve) => {
                    resolvePreview = resolve
                })
        )
        jest.mocked(lookupToolRenderer).mockReturnValue({ PermissionPreview } as ReturnType<typeof lookupToolRenderer>)
        render(<PermissionInput streamKey="run-1" request={previewRequest} />)
        expect(screen.getByText(/echo synthetic-evidence/)).toBeInTheDocument()
        fireEvent.click(screen.getByText('Allow'))
        expect(respondToPermission).toHaveBeenLastCalledWith({
            requestId: 'preview-1',
            optionId: 'allow',
            customInput: undefined,
        })

        await act(async () => resolvePreview({ default: ({ request }) => <div>Preview for {request.requestId}</div> }))
        expect(screen.getByText('Preview for preview-1')).toBeInTheDocument()
        expect(screen.queryByText(/echo synthetic-evidence/)).not.toBeInTheDocument()
        fireEvent.keyDown(document.body, { key: '2' })
        expect(respondToPermission).toHaveBeenLastCalledWith({
            requestId: 'preview-1',
            optionId: 'reject',
            customInput: undefined,
        })
    })

    it.each(['render', 'load'])('falls back after a preview %s error and keeps approvals usable', async (failure) => {
        const error = new Error('Synthetic preview failure')
        const capture = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
        const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
        const PermissionPreview =
            failure === 'load'
                ? lazy(() => Promise.reject(error))
                : ({ request }: PermissionPreviewProps): JSX.Element => {
                      if (request.requestId === 'preview-1') {
                          throw error
                      }
                      return <div>Recovered preview</div>
                  }
        jest.mocked(lookupToolRenderer).mockReturnValue({ PermissionPreview } as ReturnType<typeof lookupToolRenderer>)
        try {
            const { rerender } = render(<PermissionInput streamKey="run-1" request={previewRequest} />)
            await waitFor(() =>
                expect(capture).toHaveBeenCalledWith(
                    error,
                    expect.objectContaining({ feature: 'posthog_ai_permission_preview' })
                )
            )
            expect(screen.getByText(/echo synthetic-evidence/)).toBeInTheDocument()
            fireEvent.keyDown(document.body, { key: '1' })
            expect(respondToPermission).toHaveBeenCalledWith({
                requestId: 'preview-1',
                optionId: 'allow',
                customInput: undefined,
            })
            const NextPreview = failure === 'load' ? () => <div>Recovered preview</div> : PermissionPreview
            jest.mocked(lookupToolRenderer).mockReturnValue({ PermissionPreview: NextPreview } as ReturnType<
                typeof lookupToolRenderer
            >)
            rerender(<PermissionInput streamKey="run-1" request={{ ...previewRequest, requestId: 'preview-2' }} />)
            expect(screen.getByText('Recovered preview')).toBeInTheDocument()
            fireEvent.click(screen.getByText('Decline'))
            expect(respondToPermission).toHaveBeenLastCalledWith({
                requestId: 'preview-2',
                optionId: 'reject',
                customInput: undefined,
            })
        } finally {
            capture.mockRestore()
            consoleError.mockRestore()
        }
    })
})
