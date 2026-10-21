import { HogFunctionTemplateType } from '~/types'

// A secret input is no reason to leave a destination out: the hog flow API moves those inputs to
// `encrypted_inputs` on save, so a workflow step holds an API key the way a destination does.
export function destinationPickerFilter(
    templateIdsAtTopLevel: string[]
): (template: HogFunctionTemplateType) => boolean {
    return (template: HogFunctionTemplateType): boolean => {
        if (template.type !== 'destination' || templateIdsAtTopLevel.includes(template.id)) {
            return false
        }

        // The hog flow worker does not apply a step's mappings, so a destination that reads its fields
        // from mappings skips the event or sends empty fields. This check keeps out the mapping
        // destinations that have a secret input. Mapping destinations without one, such as Google Ads,
        // have the same gap and are still offered.
        if (template.mapping_templates?.length && template.inputs_schema?.some((input) => input.secret)) {
            return false
        }

        return !['hidden', 'coming_soon'].includes(template.status)
    }
}
