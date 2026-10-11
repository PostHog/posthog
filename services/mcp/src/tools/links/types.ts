// Shape of app-url-manifest.json, generated from the frontend's `urls` registry by
// frontend/src/scenes/appUrlManifest.ts. Kept in sync by a drift test in that same dir.
export type AppUrlScope = 'project' | 'global'

export interface AppUrlEntry {
    /** Relative path template with `{param}` placeholders, e.g. `/persons/{uuid}`. */
    template: string
    /** Placeholder names that appear in `template`, in declaration order. */
    params: string[]
    /** `project` paths get the `/project/:id` prefix; `global` paths (org/account/auth) get only the host. */
    scope: AppUrlScope
}

export type AppUrlManifest = Record<string, AppUrlEntry>
