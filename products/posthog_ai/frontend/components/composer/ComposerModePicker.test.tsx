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
        render(<ComposerModePicker selectedMode={InitialPermissionModeEnumApi.Auto} onModeChange={onModeChange} />)

        fireEvent.click(screen.getByLabelText('Mode'))

        expect(
            screen.getByText(
                'Accepts file edits and shell commands automatically. Always asks before PostHog tools that change live data. Creating or publishing content asks only while you watch the run.'
            )
        ).toBeInTheDocument()
        expect(
            screen.getByText(
                'Bypasses all permissions. Safe in the sandbox, but the agent can modify or delete data without asking.'
            )
        ).toBeInTheDocument()
        expect(
            screen.getByText(
                'Recommended for complex work such as research or implementation. Create a plan now, then execute it later.'
            )
        ).toBeInTheDocument()
        expect(screen.queryByText('Default')).not.toBeInTheDocument()
        expect(screen.queryByText('Accept edits')).not.toBeInTheDocument()

        const fullAutoOption = screen.getByText('Full auto').closest('[role="option"]')
        expect(fullAutoOption).not.toBeNull()
        fireEvent.pointerDown(fullAutoOption!, { pointerType: 'mouse' })
        fireEvent.click(fullAutoOption!)

        expect(onModeChange).toHaveBeenCalledWith(InitialPermissionModeEnumApi.BypassPermissions)
    })
})
