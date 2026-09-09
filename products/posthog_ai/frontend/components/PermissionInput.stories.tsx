import type { Meta, StoryObj } from '@storybook/react'
import { useEffect, useState } from 'react'

import type { PermissionRequestRecord } from '../types/streamTypes'
import { PermissionInput } from './PermissionInput'

const request: PermissionRequestRecord = {
    requestId: 'synthetic-permission',
    toolCallId: 'synthetic-update',
    toolName: 'mcp__posthog__exec',
    options: [
        { optionId: 'allow', name: 'Allow', kind: 'allow_once' },
        { optionId: 'reject', name: 'Decline', kind: 'reject_once' },
    ],
    rawToolCall: {
        toolCallId: 'synthetic-update',
        rawServerName: 'posthog',
        rawToolName: 'exec',
        input: { command: 'call cdp-functions-partial-update {"id":"new","name":"Updated destination"}' },
        status: 'pending',
        contentBlocks: [],
    },
}

const meta: Meta<typeof PermissionInput> = {
    title: 'Products/PostHog AI/PermissionInput',
    component: PermissionInput,
    args: { streamKey: 'synthetic-preview', request },
    decorators: [
        (Story) => (
            <div className="w-128 border rounded">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const NoMountedConfiguration: Story = {}

export const MatchingConfiguration: Story = {
    decorators: [
        (Story) => {
            const [ready, setReady] = useState(false)
            useEffect(() => {
                let disposed = false
                let unmount: (() => void) | undefined
                void import('scenes/hog-functions/configuration/hogFunctionConfigurationLogic').then(
                    ({ hogFunctionConfigurationLogic }) => {
                        if (disposed) {
                            return
                        }
                        const logic = hogFunctionConfigurationLogic({ id: 'new' })
                        unmount = logic.mount()
                        logic.actions.loadHogFunctionSuccess({
                            id: 'new',
                            type: 'destination',
                            name: 'Original destination',
                            description: '',
                            enabled: true,
                            hog: '',
                            created_by: null,
                            created_at: '2026-01-01T00:00:00Z',
                            updated_at: '2026-01-01T00:00:00Z',
                        })
                        setReady(true)
                    }
                )
                return () => {
                    disposed = true
                    unmount?.()
                }
            }, [])
            return ready ? <Story /> : <div>Preparing configuration fixture</div>
        },
    ],
}

export const MismatchedConfiguration: Story = {
    ...MatchingConfiguration,
    args: {
        request: {
            ...request,
            rawToolCall: {
                ...request.rawToolCall,
                input: {
                    command: 'call cdp-functions-partial-update {"id":"another-function","name":"Updated destination"}',
                },
            },
        },
    },
}
