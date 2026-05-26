import { RESOURCE_MIME_TYPE } from '@modelcontextprotocol/ext-apps/server'
import type {
    GetPromptResult,
    ListPromptsResult,
    ListResourcesResult,
    Prompt,
    ReadResourceResult,
    Resource,
    TextResourceContents,
} from '@modelcontextprotocol/sdk/types.js'

import {
    fetchContextMillResources,
    filterValidEntries,
    loadManifestFromArchive,
    clearResourceCache,
} from '@/resources/internals'
import { getPromptsFromManifest } from '@/resources'
import { UI_APPS } from '@/resources/ui-apps.generated'
import { buildAppStubHtml } from '@/resources/ui-apps'
import type { ContextMillResource } from '@/resources/manifest-types'
import type { Env } from '@/tools/types'

export class ResourceCatalog {
    private readonly env: Env

    private resources: Resource[] = []
    private resourcesByUri = new Map<string, TextResourceContents>()
    private prompts: Prompt[] = []
    private promptsByName = new Map<string, GetPromptResult>()
    private uiAppResources: Resource[] = []
    private uiAppReadEntries = new Map<string, TextResourceContents>()
    private allResources: Resource[] = []
    private contextMillData: readonly ContextMillResource[] = []

    constructor(env: Env) {
        this.env = env
    }

    get contextMillEntries(): readonly ContextMillResource[] {
        return this.contextMillData
    }

    async warmup(): Promise<void> {
        await Promise.all([this.warmupResources(), this.warmupUiApps()])
        this.allResources = [...this.resources, ...this.uiAppResources]
    }

    getResourcesList(): ListResourcesResult {
        return { resources: this.allResources }
    }

    readResource(params: Record<string, unknown> | undefined): ReadResourceResult {
        const uri = (params?.uri as string) ?? ''
        const entry = this.resourcesByUri.get(uri) ?? this.uiAppReadEntries.get(uri)
        if (!entry) {
            return { contents: [] }
        }
        return {
            contents: [
                {
                    uri: entry.uri,
                    mimeType: entry.mimeType,
                    text: entry.text,
                    ...(entry._meta ? { _meta: entry._meta } : {}),
                },
            ],
        }
    }

    getPromptsList(): ListPromptsResult {
        return { prompts: this.prompts }
    }

    getPrompt(params: Record<string, unknown> | undefined): GetPromptResult {
        const name = (params?.name as string) ?? ''
        const entry = this.promptsByName.get(name)
        if (!entry) {
            return { messages: [] }
        }
        return { messages: entry.messages }
    }

    private async warmupResources(): Promise<void> {
        try {
            const archive = await fetchContextMillResources()
            const manifest = loadManifestFromArchive(archive)
            this.contextMillData = filterValidEntries(manifest.resources, archive)
            clearResourceCache()

            for (const entry of this.contextMillEntries) {
                this.resources.push({
                    name: entry.name,
                    uri: entry.uri,
                    mimeType: entry.resource.mimeType,
                    description: entry.resource.description,
                })
                this.resourcesByUri.set(entry.uri, {
                    uri: entry.uri,
                    mimeType: entry.resource.mimeType,
                    text: entry.resource.text,
                })
            }
        } catch (error) {
            console.error('[ResourceCatalog] Failed to pre-load context-mill resources:', error)
        }

        try {
            const manifestPrompts = await getPromptsFromManifest()
            for (const prompt of manifestPrompts) {
                this.prompts.push({
                    name: prompt.name,
                    title: prompt.title,
                    description: prompt.description,
                })
                this.promptsByName.set(prompt.name, { messages: prompt.messages as GetPromptResult['messages'] })
            }
        } catch (error) {
            console.error('[ResourceCatalog] Failed to pre-load prompts:', error)
        }
    }

    private async warmupUiApps(): Promise<void> {
        const baseUrl = this.env.MCP_APPS_BASE_URL
        if (!baseUrl) {
            return
        }

        const analyticsBaseUrl = this.env.POSTHOG_MCP_APPS_ANALYTICS_BASE_URL

        for (const app of UI_APPS) {
            const html = buildAppStubHtml(app.appDir, baseUrl)

            const uiMetadata: Record<string, unknown> = {}
            const resourceDomains = [baseUrl]
            const connectDomains: string[] = []
            if (analyticsBaseUrl) {
                connectDomains.push(analyticsBaseUrl)
                resourceDomains.push(analyticsBaseUrl)
            }
            uiMetadata.csp = { connectDomains, resourceDomains }

            this.uiAppResources.push({
                name: app.name,
                uri: app.uri,
                mimeType: RESOURCE_MIME_TYPE,
                description: app.description,
            })
            this.uiAppReadEntries.set(app.uri, {
                uri: app.uri,
                mimeType: RESOURCE_MIME_TYPE,
                text: html,
                _meta: { ui: uiMetadata },
            })
        }
    }
}
