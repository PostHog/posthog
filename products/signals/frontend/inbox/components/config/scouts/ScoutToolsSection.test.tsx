import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { mockScoutConfigs } from '../../../__mocks__/scoutConfigs'
import { SCOUT_TOOL_CATALOGUE } from './scoutToolFixtures'
import { ScoutToolsSection } from './ScoutToolsSection'

describe('ScoutToolsSection', () => {
    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/signals/scout/configs/tool_catalogue/': () => [200, SCOUT_TOOL_CATALOGUE],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SCOUTS_TOOL_ACCESS], {
            [FEATURE_FLAGS.SCOUTS_TOOL_ACCESS]: true,
        })
    })
    afterEach(cleanup)

    const renderSection = (overrides: Partial<SignalScoutConfigApi> = {}): jest.Mock => {
        const onUpdate = jest.fn()
        render(
            <ScoutToolsSection
                config={{ ...mockScoutConfigs[0], id: 'config-1', ...overrides }}
                onUpdate={onUpdate}
                surface="scout_detail"
            />
        )
        return onUpdate
    }

    it('opens the picker without saving when someone chooses a tool list', async () => {
        // Saving an empty list here would cut the scout off from every tool before anyone picked one.
        const onUpdate = renderSection()

        fireEvent.click(screen.getByText('Chosen tools'))

        expect(await screen.findByText('Get insight')).toBeInTheDocument()
        expect(screen.getByText('Get skill')).toBeInTheDocument()
        expect(screen.getByText('Get skill file')).toBeInTheDocument()
        expect(screen.queryByLabelText(/Get skill/)).not.toBeInTheDocument()
        expect(onUpdate).not.toHaveBeenCalled()
    })

    it.each([
        ['an unchanged preset', ['Read only'], { tool_preset: 'read_only' }],
        [
            'a preset with a tool added',
            ['Read only', 'Create insight'],
            { allowed_mcp_tools: ['dashboard-get', 'insight-create', 'insight-get'] },
        ],
        ['a hand-picked list', ['Update dashboard'], { allowed_mcp_tools: ['dashboard-update'] }],
    ])('saves %s as a tool selection with no write scopes', async (_name, clicks, expected) => {
        // The API rejects `write_scopes` next to a tool selection, so the save must carry only one.
        const onUpdate = renderSection()
        fireEvent.click(screen.getByText('Chosen tools'))
        await screen.findByText('Get insight')

        for (const label of clicks) {
            fireEvent.click(screen.getByText(label))
        }
        fireEvent.click(screen.getByText('Save tools'))

        expect(onUpdate).toHaveBeenCalledWith('config-1', expected)
    })

    it('keeps an unavailable tool off the list', async () => {
        const onUpdate = renderSection({ allowed_mcp_tools: ['insight-get'] })
        fireEvent.click(screen.getByText('Edit tools'))
        await screen.findByText('Delete feature flag')

        fireEvent.click(screen.getByText('Delete feature flag'))
        fireEvent.click(screen.getByText('Save tools'))

        expect(onUpdate).not.toHaveBeenCalled()
    })

    it.each([
        ['an empty list', []],
        ['a saved list with bootstrap reads', ['skill-get', 'skill-file-get', 'insight-get']],
    ])('edits %s without submitting always-held tools', async (_name, savedTools) => {
        const onUpdate = renderSection({ allowed_mcp_tools: savedTools })
        fireEvent.click(screen.getByText('Edit tools'))
        await screen.findByText('Update dashboard')

        fireEvent.click(screen.getByText('Update dashboard'))
        fireEvent.click(screen.getByText('Save tools'))

        expect(onUpdate).toHaveBeenCalledWith('config-1', {
            allowed_mcp_tools: savedTools.length ? ['dashboard-update', 'insight-get'] : ['dashboard-update'],
        })
    })
})
