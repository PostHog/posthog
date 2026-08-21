// Shape of app-url-manifest.json, generated from the frontend's `urls` registry by
// frontend/bin/build-app-url-manifest.mjs. Kept in sync by the drift check in ci-frontend.yml.
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
