import type { EmailBrandDetectionApi, PatchedEmailBrandApi } from '../generated/api.schemas'

export const brandFields = [
    'name',
    'primary_color',
    'accent_color',
    'text_color',
    'background_color',
    'font_family',
] as const
export type BrandField = (typeof brandFields)[number]
export type BrandDraft = Required<
    Pick<PatchedEmailBrandApi, BrandField | 'logo' | 'font_stack' | 'source_repository' | 'app_root' | 'sources'>
>

export const emptyBrand: BrandDraft = {
    name: '',
    logo: null,
    primary_color: '#111111',
    accent_color: '#111111',
    text_color: '#111111',
    background_color: '#ffffff',
    font_family: 'Arial',
    font_stack: 'Arial, Helvetica, sans-serif',
    source_repository: '',
    app_root: '',
    sources: {},
}

export function detectedDraft(detection: EmailBrandDetectionApi): BrandDraft {
    const draft = {
        ...emptyBrand,
        sources: {},
        source_repository: detection.repository,
        app_root: detection.app_root,
    } as BrandDraft
    for (const field of brandFields) {
        const candidate = detection.proposal[field]
        if (candidate) {
            draft[field] = candidate.value
            if (candidate.path) {
                draft.sources[field] = { path: candidate.path, line: candidate.line, detected_value: candidate.value }
            }
        }
    }
    draft.font_stack = detection.proposal.font_family?.font_stack ?? emptyBrand.font_stack
    return draft
}

export type BrandConflicts = Partial<Record<BrandField, { value: string; font_stack?: string }>>

export function mergeDetection(
    current: BrandDraft,
    detection: EmailBrandDetectionApi,
    editedFields: string[]
): { draft: BrandDraft; conflicts: BrandConflicts } {
    const draft = detectedDraft(detection)
    const conflicts: BrandConflicts = {}
    for (const field of brandFields) {
        if (editedFields.includes(field) && current[field] !== draft[field]) {
            conflicts[field] = {
                value: draft[field],
                ...(field === 'font_family' ? { font_stack: draft.font_stack } : {}),
            }
            draft[field] = current[field]
            if (field === 'font_family') {
                draft.font_stack = current.font_stack
            }
        }
    }
    draft.logo = current.logo
    if (current.sources.logo) {
        draft.sources.logo = current.sources.logo
    }
    return { draft, conflicts }
}
