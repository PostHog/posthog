import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { DebugLogsMenu } from './DebugLogsMenu'

// The menu is driven entirely by `debugLogsLogic`, which reads `userLogic` and `preflightLogic`. Storybook's
// default mock user is staff, so the `Staff` stories render the trigger; `NonStaff` overrides the user to
// show the other branch, where the whole component collapses to null.
const meta: Meta<typeof DebugLogsMenu> = {
    title: 'Products/PostHog AI/DebugLogsMenu',
    component: DebugLogsMenu,
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof DebugLogsMenu>

/** Small secondary button, matching the `/ai` header. Open it to reach the switch. */
export const StaffLemon: Story = {
    args: { variant: 'lemon' },
}

/** Icon-only chrome, matching the side-panel header. */
export const StaffPrimitive: Story = {
    args: { variant: 'primitive' },
}

/**
 * A non-staff viewer gets no trigger at all, so the header shows no empty affordance. Renders blank on
 * purpose. `is_debug` has to be mocked off too: the default preflight fixture sets it, which makes
 * `isDev` true and would grant control regardless of the user.
 */
export const NonStaff: Story = {
    args: { variant: 'lemon' },
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, is_staff: false, is_impersonated: false }],
                '/_preflight': () => [200, { ...preflightJson, is_debug: false }],
            },
        }),
    ],
}
