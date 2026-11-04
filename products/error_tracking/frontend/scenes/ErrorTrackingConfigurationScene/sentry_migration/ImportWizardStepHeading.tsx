import { ReactNode } from 'react'

export interface ImportWizardStepHeadingProps {
    title: string
    description: ReactNode
}

export function ImportWizardStepHeading({ title, description }: ImportWizardStepHeadingProps): JSX.Element {
    return (
        <div>
            <h3 className="text-lg font-semibold mb-1">{title}</h3>
            <p className="text-secondary text-sm mb-0">{description}</p>
        </div>
    )
}
