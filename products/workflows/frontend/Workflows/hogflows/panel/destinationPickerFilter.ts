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

        return !['hidden', 'coming_soon'].includes(template.status)
    }
}
