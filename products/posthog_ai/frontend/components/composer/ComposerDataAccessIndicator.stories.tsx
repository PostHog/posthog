import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { organizationLogic } from 'scenes/organizationLogic'

import { Composer } from './Composer'
import { ComposerDataAccessIndicator } from './ComposerDataAccessIndicator'

type Story = StoryObj<typeof ComposerDataAccessIndicator>

function WithNoDataAccess({ children }: { children: JSX.Element }): JSX.Element {
    const { loadCurrentOrganizationSuccess } = useActions(organizationLogic)
    useEffect(() => {
        loadCurrentOrganizationSuccess({ ...MOCK_DEFAULT_ORGANIZATION, ai_data_access: 'metadata_only' })
    }, [loadCurrentOrganizationSuccess])
    return children
}

const meta: Meta<typeof ComposerDataAccessIndicator> = {
    title: 'Products/PostHog AI/Composer data access',
    component: ComposerDataAccessIndicator,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        (Story) => (
            <WithNoDataAccess>
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
            </WithNoDataAccess>
        ),
    ],
}
export default meta

export const NoDataAccess: Story = {}
