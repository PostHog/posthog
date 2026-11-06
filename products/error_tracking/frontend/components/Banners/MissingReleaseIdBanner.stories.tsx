import { Meta } from '@storybook/react'

import { StyleVariables } from '../StyleVariables'
import { MissingReleaseIdBanner } from './MissingReleaseIdBanner'

const meta: Meta = {
    title: 'ErrorTracking/MissingReleaseIdBanner',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    decorators: [
        (Story: React.FC): JSX.Element => (
            <StyleVariables>
                <div className="w-[600px]">
                    <Story />
                </div>
            </StyleVariables>
        ),
    ],
}

export default meta

export function Default(): JSX.Element {
    return <MissingReleaseIdBanner eventId="event-id" runtime="web" />
}
