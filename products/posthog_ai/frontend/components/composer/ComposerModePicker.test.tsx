import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { InitialPermissionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { ComposerModePicker } from './ComposerModePicker'

describe('ComposerModePicker', () => {
    afterEach(() => {
        cleanup()
    })

    it('shows the three product modes with their safety guidance and emits their server values', () => {
        const onModeChange = jest.fn()
        render(
            <ComposerModePicker
                selectedMode={InitialPermissionModeEnumApi.BypassPermissions}
                onModeChange={onModeChange}
            />
        )

        fireEvent.click(screen.getByLabelText('Mode'))

        expect(
            screen.getByText(
                'Bypasses all permissions. Safe in the sandbox, but the agent can modify or delete data without asking.'
            )
        ).toBeInTheDocument()
        expect(
            screen.getByText(
                'Accepts file edits automatically. Bash commands and PostHog MCP tools that update or delete data still require approval.'
            )
        ).toBeInTheDocument()
        expect(
            screen.getByText(
                'Recommended for complex work such as research or implementation. Create a plan now, then execute it later.'
            )
        ).toBeInTheDocument()
        expect(screen.queryByText('Default')).not.toBeInTheDocument()
        expect(screen.queryByText('Bypass permissions')).not.toBeInTheDocument()

        const acceptEditsOption = screen.getByText('Accept edits').closest('[role="option"]')
        expect(acceptEditsOption).not.toBeNull()
        fireEvent.pointerDown(acceptEditsOption!, { pointerType: 'mouse' })
        fireEvent.click(acceptEditsOption!)

        expect(onModeChange).toHaveBeenCalledWith(InitialPermissionModeEnumApi.AcceptEdits)
    })
})
