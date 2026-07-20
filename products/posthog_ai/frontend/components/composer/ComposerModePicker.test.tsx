import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { InitialPermissionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { ComposerModePicker } from './ComposerModePicker'

describe('ComposerModePicker', () => {
    afterEach(() => {
        cleanup()
    })

    it('shows the three product modes with one description at a time and emits their server values', () => {
        const onModeChange = jest.fn()
        render(<ComposerModePicker selectedMode={InitialPermissionModeEnumApi.Auto} onModeChange={onModeChange} />)

        fireEvent.click(screen.getByLabelText('Mode'))

        expect(screen.queryByText('Default')).not.toBeInTheDocument()
        expect(screen.queryByText('Accept edits')).not.toBeInTheDocument()

        // The footer describes the selected mode on open; the other descriptions stay out of the menu.
        expect(
            screen.getByText(
                'Accepts file edits and shell commands automatically. Always asks before PostHog tools that change live data. Creating or publishing content asks only while you watch the run.'
            )
        ).toBeInTheDocument()
        expect(
            screen.queryByText('Never asks. The agent can change or delete live data on its own.')
        ).not.toBeInTheDocument()

        const fullAutoOption = screen.getByText('Full auto').closest('[role="option"]')
        expect(fullAutoOption).not.toBeNull()
        fireEvent.pointerDown(fullAutoOption!, { pointerType: 'mouse' })
        fireEvent.click(fullAutoOption!)

        expect(onModeChange).toHaveBeenCalledWith(InitialPermissionModeEnumApi.BypassPermissions)
    })
})
