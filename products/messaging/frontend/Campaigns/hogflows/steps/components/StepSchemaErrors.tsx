import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { campaignLogic } from '../../../campaignLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'

export function StepSchemaErrors(): JSX.Element | null {
    const { selectedNode } = useValues(hogFlowEditorLogic)
    const { actionValidationErrorsById } = useValues(campaignLogic)
    const validationResult = actionValidationErrorsById[selectedNode?.id ?? '']

    if (!validationResult?.schema) {
        return null
    }

    return (
        <div className="flex flex-col gap-1">
            {Object.values(validationResult.schema.errors).map(({ path, message }) => (
                <LemonBanner type="error" key={path.join('.')}>
                    {path.join('.')}: {message}
                </LemonBanner>
            ))}
        </div>
    )
}
