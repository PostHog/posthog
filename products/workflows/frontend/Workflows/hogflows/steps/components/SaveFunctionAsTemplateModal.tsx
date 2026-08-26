import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import type { CyclotronJobInputType, HogFunctionMappingType, HogFunctionTemplateType } from '~/types'

import { savedFunctionTemplatesLogic } from '../../savedFunctionTemplatesLogic'
import { stripSecretInputs } from '../../stripSecretInputs'

export function SaveFunctionAsTemplateModal({
    template,
    inputs,
    mappings,
}: {
    template: HogFunctionTemplateType
    inputs: Record<string, CyclotronJobInputType>
    mappings?: HogFunctionMappingType[]
}): JSX.Element {
    const { saveModalOpen, savedFunctionTemplatesLoading } = useValues(savedFunctionTemplatesLogic)
    const { closeSaveModal, saveFunctionTemplate } = useActions(savedFunctionTemplatesLogic)

    const [templateName, setTemplateName] = useState('')
    const [templateDescription, setTemplateDescription] = useState('')

    useEffect(() => {
        if (saveModalOpen) {
            setTemplateName('')
            setTemplateDescription('')
        }
    }, [saveModalOpen])

    const { inputs: cleanInputs, strippedKeys: inputStrippedKeys } = stripSecretInputs(
        inputs ?? {},
        template.inputs_schema
    )
    // Mappings carry their own inputs and inputs_schema, so strip each one by its own schema
    const cleanedMappings = mappings?.map((mapping) => {
        const { inputs: cleanMappingInputs, strippedKeys: mappingStrippedKeys } = stripSecretInputs(
            mapping.inputs ?? {},
            mapping.inputs_schema
        )
        return { mapping: { ...mapping, inputs: cleanMappingInputs }, strippedKeys: mappingStrippedKeys }
    })
    const strippedKeys = Array.from(
        new Set([...inputStrippedKeys, ...(cleanedMappings ?? []).flatMap((m) => m.strippedKeys)])
    )

    const handleClose = (): void => {
        setTemplateName('')
        setTemplateDescription('')
        closeSaveModal()
    }

    return (
        <LemonModal
            isOpen={saveModalOpen}
            onClose={handleClose}
            title="Save as template"
            description="Save this step to your library so you can reuse it in other workflows"
            footer={
                <>
                    <LemonButton onClick={handleClose}>Cancel</LemonButton>
                    <LemonButton
                        type="primary"
                        loading={savedFunctionTemplatesLoading}
                        onClick={() =>
                            saveFunctionTemplate({
                                name: templateName,
                                description: templateDescription,
                                templateId: template.id,
                                inputs: cleanInputs,
                                mappings: cleanedMappings?.map((m) => m.mapping),
                            })
                        }
                        disabledReason={!templateName ? 'Please enter a template name' : undefined}
                    >
                        Save template
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                {strippedKeys.length > 0 && (
                    <LemonBanner type="info">
                        Secret fields ({strippedKeys.join(', ')}) are not saved to the library. You enter them again in
                        each workflow that uses this template.
                    </LemonBanner>
                )}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Template name</LemonLabel>
                    <LemonInput
                        placeholder="My webhook"
                        value={templateName}
                        onChange={setTemplateName}
                        autoFocus
                        data-attr="function-template-name"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel showOptional>Description</LemonLabel>
                    <LemonTextArea
                        placeholder="Describe when to use this template..."
                        value={templateDescription}
                        onChange={setTemplateDescription}
                        rows={3}
                    />
                </div>
            </div>
        </LemonModal>
    )
}
