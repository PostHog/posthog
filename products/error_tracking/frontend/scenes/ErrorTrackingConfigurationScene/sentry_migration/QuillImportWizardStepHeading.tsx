import { Heading, Text } from '@posthog/quill'

import type { ImportWizardStepHeadingProps } from './ImportWizardStepHeading'

export function QuillImportWizardStepHeading({ title, description }: ImportWizardStepHeadingProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <Heading size="sm" render={<h3 className="m-0" />}>
                {title}
            </Heading>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                {description}
            </Text>
        </div>
    )
}
