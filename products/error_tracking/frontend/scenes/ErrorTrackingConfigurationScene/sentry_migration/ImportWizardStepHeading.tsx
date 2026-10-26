import { ReactNode } from 'react'

import { Heading, Text } from '@posthog/quill'

export interface ImportWizardStepHeadingProps {
    title: string
    description: ReactNode
}

export function ImportWizardStepHeading({ title, description }: ImportWizardStepHeadingProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <Heading size="lg" render={<h3 className="m-0" />}>
                {title}
            </Heading>
            <Text size="xs" variant="muted" className="m-0">
                {description}
            </Text>
        </div>
    )
}
