import type { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

/** Drop inputs marked secret in the template schema — the template library stores plaintext JSON,
 * so secrets must never be saved into it. Returns the dropped keys so the UI can tell the user. */
export function stripSecretInputs(
    inputs: Record<string, CyclotronJobInputType>,
    inputsSchema: CyclotronJobInputSchemaType[] | undefined | null
): { inputs: Record<string, CyclotronJobInputType>; strippedKeys: string[] } {
    const secretKeys = new Set((inputsSchema ?? []).filter((schema) => schema.secret).map((schema) => schema.key))
    const cleanInputs: Record<string, CyclotronJobInputType> = {}
    const strippedKeys: string[] = []
    for (const [key, value] of Object.entries(inputs)) {
        if (secretKeys.has(key)) {
            strippedKeys.push(key)
        } else {
            cleanInputs[key] = value
        }
    }
    return { inputs: cleanInputs, strippedKeys }
}
