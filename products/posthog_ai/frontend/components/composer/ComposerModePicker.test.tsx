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

        // Hovering another option swaps the footer to its description. This breaks if ModeItemRow
        // stops forwarding Base UI's ref — the item then never registers for hover highlighting.
        const fullAutoOption = screen.getByText('Full auto').closest('[role="option"]')
        expect(fullAutoOption).not.toBeNull()
        fireEvent.mouseMove(fullAutoOption!)
        expect(screen.getByText('Never asks. The agent can change or delete live data on its own.')).toBeInTheDocument()
        expect(
            screen.queryByText(
                'Accepts file edits and shell commands automatically. Always asks before PostHog tools that change live data. Creating or publishing content asks only while you watch the run.'
            )
        ).not.toBeInTheDocument()

        fireEvent.pointerDown(fullAutoOption!, { pointerType: 'mouse' })
        fireEvent.click(fullAutoOption!)

        expect(onModeChange).toHaveBeenCalledWith(InitialPermissionModeEnumApi.BypassPermissions)
    })

    it('never describes a mode the narrowed menu does not offer', () => {
        render(
            <ComposerModePicker
                selectedMode={InitialPermissionModeEnumApi.Auto}
                onModeChange={jest.fn()}
                modes={[InitialPermissionModeEnumApi.Plan, InitialPermissionModeEnumApi.BypassPermissions]}
            />
        )

        fireEvent.click(screen.getByLabelText('Mode'))

        // The selected mode is filtered out, so the footer falls back to an offered mode's description.
        expect(screen.getByText('Never asks. The agent can change or delete live data on its own.')).toBeInTheDocument()
        expect(
            screen.queryByText(
                'Accepts file edits and shell commands automatically. Always asks before PostHog tools that change live data. Creating or publishing content asks only while you watch the run.'
            )
        ).not.toBeInTheDocument()
    })
})
