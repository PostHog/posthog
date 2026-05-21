import { RESOURCE_MIME_TYPE } from '@modelcontextprotocol/ext-apps/server'
import type { GetPromptResult, Prompt, Resource, TextResourceContents } from '@modelcontextprotocol/sdk/types.js'

import { fetchContextMillResources, filterValidEntries, loadManifestFromArchive, clearResourceCache } from '@/resources/internals'
import { getPromptsFromManifest } from '@/resources'
import { UI_APPS } from '@/resources/ui-apps.generated'
import { buildAppStubHtml } from '@/resources/ui-apps'
import type { ContextMillResource } from '@/resources/manifest-types'
import type { Env } from '@/tools/types'

export class ResourceCatalog {
    private readonly env: Env

    private _resources: Resource[] = []
    private _resourcesByUri = new Map<string, TextResourceContents>()
    private _prompts: Prompt[] = []
    private _promptsByName = new Map<string, GetPromptResult>()
    private _uiAppResources: Resource[] = []
    private _uiAppReadEntries = new Map<string, TextResourceContents>()
    private _allResources: Resource[] = []
    private _contextMillEntries: readonly ContextMillResource[] = []

    constructor(env: Env) {
        this.env = env
    }

    get contextMillEntries(): readonly ContextMillResource[] {
        return this._contextMillEntries
    }

    async warmup(): Promise<void> {
        await Promise.all([this._warmupResources(), this._warmupUiApps()])
        this._allResources = [...this._resources, ...this._uiAppResources]
    }

    getResourcesList(): { resources: Resource[] } {
        return { resources: this._allResources }
    }

    readResource(params: Record<string, unknown> | undefined): unknown {
        const uri = (params?.uri as string) ?? ''
        const entry = this._resourcesByUri.get(uri) ?? this._uiAppReadEntries.get(uri)
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

    getPromptsList(): { prompts: Prompt[] } {
        return { prompts: this._prompts }
    }

    getPrompt(params: Record<string, unknown> | undefined): unknown {
        const name = (params?.name as string) ?? ''
        const entry = this._promptsByName.get(name)
        if (!entry) {
            return { messages: [] }
        }
        return { messages: entry.messages }
    }

    private async _warmupResources(): Promise<void> {
        try {
            const archive = await fetchContextMillResources()
            const manifest = loadManifestFromArchive(archive)
            this._contextMillEntries = filterValidEntries(manifest.resources, archive)
            clearResourceCache()

            for (const entry of this._contextMillEntries) {
                this._resources.push({
                    name: entry.name,
                    uri: entry.uri,
                    mimeType: entry.resource.mimeType,
                    description: entry.resource.description,
                })
                this._resourcesByUri.set(entry.uri, {
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
                this._prompts.push({
                    name: prompt.name,
                    title: prompt.title,
                    description: prompt.description,
                })
                this._promptsByName.set(prompt.name, { messages: prompt.messages as GetPromptResult['messages'] })
            }
        } catch (error) {
            console.error('[ResourceCatalog] Failed to pre-load prompts:', error)
        }
    }

    private async _warmupUiApps(): Promise<void> {
        const baseUrl = this.env.MCP_APPS_BASE_URL
        if (!baseUrl) {return}

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

            this._uiAppResources.push({
                name: app.name,
                uri: app.uri,
                mimeType: RESOURCE_MIME_TYPE,
                description: app.description,
            })
            this._uiAppReadEntries.set(app.uri, {
                uri: app.uri,
                mimeType: RESOURCE_MIME_TYPE,
                text: html,
                _meta: { ui: uiMetadata },
            })
        }
    }
}
