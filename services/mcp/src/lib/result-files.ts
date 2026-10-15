import type { Schemas } from '@/api/generated'
import { MCP_OPENAI_RESULT_FILES_FEATURE_FLAG } from '@/hono/constants'
import type { ResolvedState } from '@/hono/request-state-resolver'
import type { ToolResultPayload } from '@/lib/build-tool-result'
import { APP_DATA_META_KEY } from '@/ui-apps/types'

export const RESULT_FILE_THRESHOLD_BYTES = 32 * 1024
const RESULT_FILE_MAX_BYTES = 8 * 1024 * 1024
const RESULT_FILE_PREVIEW_CHARS = 2000
const RESULT_FILE_UPLOAD_TIMEOUT_MS = 5000

export async function offloadToolResult(response: ToolResultPayload, state: ResolvedState): Promise<ToolResultPayload> {
    if (
        response.isError ||
        state.toolFeatureFlags?.[MCP_OPENAI_RESULT_FILES_FEATURE_FLAG] !== true ||
        !state.clientProfile.isOpenAIClient()
    ) {
        return response
    }

    try {
        const { _meta: _appMeta, __execBuiltPayload: _brand, ...fileResult } = response
        const content = JSON.stringify(fileResult)
        const sizeBytes = Buffer.byteLength(content, 'utf8')
        if (sizeBytes <= RESULT_FILE_THRESHOLD_BYTES || sizeBytes > RESULT_FILE_MAX_BYTES) {
            return response
        }
        const projectId = await state.context.stateManager.getProjectId()
        const stored = await state.context.api.request<Schemas.MCPStoredResultResponse>({
            method: 'POST',
            path: `/api/projects/${projectId}/mcp_tools/results/store/`,
            body: { content },
            timeoutMs: RESULT_FILE_UPLOAD_TIMEOUT_MS,
            retry: false,
        })
        const { structuredContent, ...inlineResult } = response
        if (structuredContent) {
            inlineResult._meta = { ...inlineResult._meta, [APP_DATA_META_KEY]: structuredContent }
        }
        return {
            ...inlineResult,
            content: [
                {
                    type: 'text',
                    text: JSON.stringify({
                        download_url: stored.download_url,
                        expires_in: stored.expires_in,
                        size_bytes: sizeBytes,
                        content_type: 'application/json',
                        instructions:
                            'Download the file to read the complete MCP tool response. It contains content and, when present, structuredContent. Filter or aggregate it locally. The preview is incomplete.',
                        preview: response.content
                            .map((part) => part.text)
                            .join('\n')
                            .slice(0, RESULT_FILE_PREVIEW_CHARS),
                    }),
                },
            ],
        }
    } catch {
        console.warn('[MCP] Could not store the result file; returning the inline response')
        return response
    }
}
