import posthog from 'posthog-js'

import { workflowEmailDraftsCreate } from '../generated/api'
import { type EmailDraftApi, type EmailDraftRequestApi, EmailDraftSourceEnumApi } from '../generated/api.schemas'
import { MessageDraft, parseMessageDraftPrefill } from './messageDrafts'

// pinned: URL search param, entry points link to /broadcasts/new and /workflows/new with it
export const DRAFT_SOURCE_PARAM = 'draft_source'

// The endpoint bounds the model call itself. This only stops the loading state hanging on a stuck request.
const REQUEST_TIMEOUT_MS = 20000

export type AiEmailDraftSurface = 'broadcast' | 'workflow'

export interface AiEmailDraftResult {
    draft: MessageDraft | null
    generatedBy: EmailDraftApi['generated_by']
    /** The endpoint's `template_reason`, or `request_failed` when the request itself failed. */
    templateReason: string | null
}

export function parseEmailDraftSource(raw: unknown): EmailDraftRequestApi | null {
    let value = raw
    if (typeof raw === 'string') {
        try {
            value = JSON.parse(raw)
        } catch {
            return null
        }
    }
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return null
    }
    const { source, source_id } = value as Record<string, unknown>
    const sources: readonly unknown[] = Object.values(EmailDraftSourceEnumApi)
    if (!sources.includes(source) || (typeof source_id !== 'string' && typeof source_id !== 'number')) {
        return null
    }
    const id = String(source_id)
    return id ? { source: source as EmailDraftRequestApi['source'], source_id: id } : null
}

export async function requestAiEmailDraft(
    projectId: string,
    request: EmailDraftRequestApi
): Promise<AiEmailDraftResult> {
    let response: EmailDraftApi
    try {
        response = await workflowEmailDraftsCreate(projectId, request, {
            signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
        })
    } catch {
        return { draft: null, generatedBy: 'template', templateReason: 'request_failed' }
    }
    if (response.generated_by !== 'ai') {
        return { draft: null, generatedBy: 'template', templateReason: response.template_reason ?? null }
    }
    const draft = parseMessageDraftPrefill({
        subject: response.subject,
        paragraphs: response.text
            .split(/\n{2,}/)
            .map((paragraph) => paragraph.trim())
            .filter(Boolean),
    })
    if (!draft) {
        return { draft: null, generatedBy: 'template', templateReason: 'invalid_output' }
    }
    return {
        draft: { ...draft, preheader: response.preheader.trim() || undefined },
        generatedBy: 'ai',
        templateReason: null,
    }
}

export type AiEmailDraftSkipReason = 'edited' | 'saved'

export function captureAiEmailDraft(
    surface: AiEmailDraftSurface,
    request: EmailDraftRequestApi,
    result: AiEmailDraftResult,
    skipped: AiEmailDraftSkipReason | null
): void {
    // pinned: analytics event name
    posthog.capture('email draft prefilled', {
        surface,
        source: request.source,
        generated_by: result.generatedBy,
        template_reason: result.templateReason,
        applied: !!result.draft && !skipped,
        skipped_reason: result.draft ? skipped : null,
    })
}
