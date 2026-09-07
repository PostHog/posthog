import type { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import {
    mockScoutConfigs,
    mockScoutRuns,
    mockScoutSuggestions,
    mockScoutSuggestionSet,
} from '../../../__mocks__/scoutConfigs'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { ScoutsRoster } from './ScoutsRoster'

// The "Suggested for this project" strip above the roster. Use these to check how the batch reads
// when it has aged, when it shrank to one pick, and when the last scan failed.

const SUGGESTIONS_URL = '/api/projects/:id/signals/scout/suggestions/'

/** The strip opens collapsed, so the stories open it unless one asks for the collapsed line. */
function StripState({ collapsed, children }: { collapsed: boolean; children: React.ReactNode }): JSX.Element {
    const logic = useMountedLogic(scoutSuggestionsLogic)
    useEffect(() => {
        logic.actions.showStrip()
        logic.actions.setCollapsed(collapsed)
    }, [logic, collapsed])
    return <>{children}</>
}

const meta: Meta<typeof ScoutsRoster> = {
    title: 'Scenes-App/Inbox/ScoutSuggestionsStrip',
    component: ScoutsRoster,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-11',
        featureFlags: {
            [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
            [FEATURE_FLAGS.INBOX_REDESIGN]: true,
            [FEATURE_FLAGS.SCOUTS_SUGGESTIONS_UI]: true,
        },
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        (Story, { parameters }) => (
            <StripState collapsed={parameters.stripCollapsed === true}>
                <Story />
            </StripState>
        ),
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/configs/': () => [200, mockScoutConfigs],
                '/api/projects/:id/signals/scout/runs/recent-per-scout/': () => [200, mockScoutRuns(mockScoutConfigs)],
                '/api/projects/:id/signals/scout/runs/findings/summary/': () => [200, null],
                '/api/projects/:id/signals/scout/metadata/current/': () => [200, null],
                '/api/projects/:id/signals/scout/scratchpad/': () => [200, []],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof ScoutsRoster>

export const Fresh: Story = {
    decorators: [mswDecorator({ get: { [SUGGESTIONS_URL]: () => [200, mockScoutSuggestionSet()] } })],
}

// How the strip opens on a first visit: one line naming the picks, until the chevron opens it.
export const Collapsed: Story = {
    parameters: { stripCollapsed: true },
    decorators: [mswDecorator({ get: { [SUGGESTIONS_URL]: () => [200, mockScoutSuggestionSet()] } })],
}

// The steady state: any scout turned on or off since the scan flips the batch to stale. The picks
// are still valid, so this is a footer note rather than an error.
export const Stale: Story = {
    decorators: [
        mswDecorator({
            get: { [SUGGESTIONS_URL]: () => [200, mockScoutSuggestionSet({ status: 'stale' })] },
        }),
    ],
}

// A batch shrinks on its own as its picks get created, so one card has to look deliberate.
export const SingleCard: Story = {
    decorators: [
        mswDecorator({
            get: { [SUGGESTIONS_URL]: () => [200, mockScoutSuggestionSet({ items: [mockScoutSuggestions[1]] })] },
        }),
    ],
}

// The prior picks stay on screen when a scan fails, since they are still the best batch we have.
export const LastScanFailed: Story = {
    decorators: [
        mswDecorator({
            get: { [SUGGESTIONS_URL]: () => [200, mockScoutSuggestionSet({ status: 'failed' })] },
        }),
    ],
}

// Every pick acted on or dismissed. The header line stays so Refresh is still reachable.
export const NothingLeft: Story = {
    decorators: [
        mswDecorator({
            get: { [SUGGESTIONS_URL]: () => [200, mockScoutSuggestionSet({ items: [] })] },
        }),
    ],
}

// No batch has ever been generated, so the roster looks exactly as it did before the strip existed.
export const NeverGenerated: Story = {
    decorators: [
        mswDecorator({
            get: {
                [SUGGESTIONS_URL]: () => [
                    200,
                    mockScoutSuggestionSet({ status: 'empty', generated_at: null, items: [] }),
                ],
            },
        }),
    ],
}

// An empty fleet gets the same cards as the body of the empty state.
export const EmptyFleet: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/configs/': () => [200, []],
                '/api/projects/:id/signals/scout/runs/recent-per-scout/': () => [200, []],
                [SUGGESTIONS_URL]: () => [200, mockScoutSuggestionSet()],
            },
        }),
    ],
}

// The narrow scene a sidebar plus an open side panel leaves: the card grid drops to one column.
export const Narrow: Story = {
    parameters: {
        testOptions: { viewport: { width: 600, height: 900 }, waitForLoadersToDisappear: false },
    },
    decorators: [mswDecorator({ get: { [SUGGESTIONS_URL]: () => [200, mockScoutSuggestionSet()] } })],
}
