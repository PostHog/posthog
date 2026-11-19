import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { ModelAccessEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { Composer } from './Composer'
import { ComposerCodexBillingIndicator } from './ComposerCodexBillingIndicator'

type Story = StoryObj<typeof ComposerCodexBillingIndicator>

const meta: Meta<typeof ComposerCodexBillingIndicator> = {
    title: 'Products/PostHog AI/Composer billing',
    component: ComposerCodexBillingIndicator,
    parameters: {
        featureFlags: [FEATURE_FLAGS.PHAI_SANDBOX_MODE, FEATURE_FLAGS.POSTHOG_CODE_CODEX_OWN_SUBSCRIPTION_CLOUD],
        testOptions: { snapshotBrowsers: [] },
        msw: { mocks: { get: { '/api/users/@me/integrations/codex/': { status: 'not_connected' } } } },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/users/@me/integrations/codex/': { status: 'connected', email: 'alex@example.com' },
            },
        }),
        (Story) => (
            <div className="mx-auto w-full max-w-180 p-4" data-quill>
                <Composer.Root value="" onChange={() => {}} onSubmit={() => {}}>
                    <Composer.Frame>
                        <Composer.Field>
                            <Composer.Placeholder>Ask anything…</Composer.Placeholder>
                            <Composer.Textarea />
                        </Composer.Field>
                        <Composer.Footer className="justify-end">
                            <Story />
                        </Composer.Footer>
                    </Composer.Frame>
                </Composer.Root>
            </div>
        ),
    ],
}
export default meta

export const NotConnected: Story = {}

export const Connected: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/users/@me/integrations/codex/': { status: 'connected', email: 'alex@example.com' },
                },
            },
        },
    },
}

export const Reconnect: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/users/@me/integrations/codex/': { status: 'reauth_required' },
                },
            },
        },
    },
}

export const ConnectionError: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/users/@me/integrations/codex/': () => [500, {}],
                },
            },
        },
    },
}

export const ActiveRun: Story = {
    args: { lockedCodexModelAccess: ModelAccessEnumApi.OwnSubscription },
}
