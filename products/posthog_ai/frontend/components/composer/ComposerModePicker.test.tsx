import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { InitialPermissionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { ComposerModePicker } from './ComposerModePicker'

describe('ComposerModePicker', () => {
    afterEach(() => {
        cleanup()
    })

    it('shows the runtime\u2019s modes with one description at a time and emits their server values', () => {
        const onModeChange = jest.fn()
        render(<ComposerModePicker selectedMode={InitialPermissionModeEnumApi.Auto} onModeChange={onModeChange} />)

        fireEvent.click(screen.getByLabelText('Mode'))

        // Claude's own set, in its own order — Codex's `read-only` / `full access` belong to the other runtime.
        expect(screen.getByText('Default')).toBeInTheDocument()
        expect(screen.getByText('Accept edits')).toBeInTheDocument()
        expect(screen.queryByText('Read only')).not.toBeInTheDocument()
        expect(screen.queryByText('Full access')).not.toBeInTheDocument()
        // Never-ask modes are gated out, as they are in the desktop app by default.
        expect(screen.queryByText('Full auto')).not.toBeInTheDocument()

        // The strip renders twice (top and bottom edge, CSS picks one by open direction).
        const strips = screen.getAllByText(
            'Accepts file edits and shell commands automatically. Always asks before PostHog tools that change live data. Creating or publishing content asks only while you watch the run.'
        )
        expect(strips).not.toHaveLength(0)
        // Inside the popup, its overflow and scroll mask hide the strips entirely.
        for (const strip of strips) {
            expect(strip.closest('[data-slot="select-content"]')).toBeNull()
        }
        expect(
            screen.queryByText('Plans the work first. Nothing runs until you approve the plan.')
        ).not.toBeInTheDocument()

        // Hovering another option swaps the strip to its description. This breaks if ModeItemRow
        // stops forwarding Base UI's ref — the item then never registers for hover highlighting.
        const planOption = screen.getByText('Plan').closest('[role="option"]')
        expect(planOption).not.toBeNull()
        fireEvent.mouseMove(planOption!)
        expect(screen.getAllByText('Plans the work first. Nothing runs until you approve the plan.')).not.toHaveLength(
            0
        )
        expect(
            screen.queryByText(
                'Accepts file edits and shell commands automatically. Always asks before PostHog tools that change live data. Creating or publishing content asks only while you watch the run.'
            )
        ).not.toBeInTheDocument()

        fireEvent.pointerDown(planOption!, { pointerType: 'mouse' })
        fireEvent.click(planOption!)

        expect(onModeChange).toHaveBeenCalledWith(InitialPermissionModeEnumApi.Plan)
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

        // The selected mode is filtered out, so the strip falls back to the first offered mode.
        expect(screen.getAllByText('Plans the work first. Nothing runs until you approve the plan.')).not.toHaveLength(
            0
        )
        expect(
            screen.queryByText(
                'Accepts file edits and shell commands automatically. Always asks before PostHog tools that change live data. Creating or publishing content asks only while you watch the run.'
            )
        ).not.toBeInTheDocument()
    })
})
