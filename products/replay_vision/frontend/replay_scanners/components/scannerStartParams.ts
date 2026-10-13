/**
 * Search params to carry into the editor when a template card starts the flow. The chosen card owns
 * the `template` key outright: the blank card must not inherit one an earlier pick left in the URL,
 * because downstream readers treat it as the source of the config, so a stale key locks the type
 * selector and makes the editor claim the template supplied the categories.
 */
export function scannerStartSearchParams(
    searchParams: Record<string, unknown>,
    templateKey: string | null
): Record<string, unknown> {
    const { template: _staleTemplate, ...params } = searchParams
    return templateKey ? { ...params, template: templateKey } : params
}
