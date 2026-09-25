// A Connect click can name a template the catalog no longer serves: the catalog
// serves only the templates available to this project, and a registered gateway
// row outlives its template.
export const TEMPLATE_UNAVAILABLE_REASON =
    'This server is no longer in the catalog. Refresh the page for the current list.'

export function isTemplateUnavailable(error: unknown): boolean {
    if (typeof error !== 'object' || error === null || !('data' in error)) {
        return false
    }
    const data = (error as { data?: unknown }).data
    return typeof data === 'object' && data !== null && (data as { reason?: unknown }).reason === 'template_unavailable'
}
