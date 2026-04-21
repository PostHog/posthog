import { existsSync, readdirSync } from 'fs'
import { resolve } from 'path'

export const MCP_ROOT_DIR = resolve(__dirname, '..')
export const ROOT_DIR = resolve(MCP_ROOT_DIR, '..', '..')
export const APPS_DIR = resolve(MCP_ROOT_DIR, 'src/ui-apps/apps')

/**
 * Auto-discover UI apps from src/ui-apps/apps/ and generated/ subdirectory.
 * Returns app names like "debug", "query-results", "generated/action", etc.
 */
export function discoverApps(): string[] {
    // Top-level custom/manual apps
    const apps = readdirSync(APPS_DIR)
        .filter((f) => f.endsWith('.tsx'))
        .map((f) => f.replace(/\.tsx$/, ''))

    // Generated apps in the generated/ subdirectory
    const generatedDir = resolve(APPS_DIR, 'generated')
    if (existsSync(generatedDir)) {
        for (const f of readdirSync(generatedDir)) {
            if (f.endsWith('.tsx')) {
                apps.push(`generated/${f.replace(/\.tsx$/, '')}`)
            }
        }
    }

    return apps
}
