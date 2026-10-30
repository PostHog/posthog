import type { ProjectScope } from '@/api/reports'

// Links that hand off to the web. Shortcut hrefs carry no project prefix, so the project goes in front.

/** The web page of a view, from its shortcut `href` such as `/dashboard/12`. Undefined without a project (demo). */
export function viewWebUrl(scope: ProjectScope | null, href: string | null): string | undefined {
    if (!scope || !href) {
        return undefined
    }
    return `${scope.host}/project/${scope.projectId}${href.startsWith('/') ? href : `/${href}`}`
}

export function navListWebUrl(scope: ProjectScope | null, list: 'errors' | 'replay'): string | undefined {
    return viewWebUrl(scope, list === 'errors' ? '/error_tracking' : '/replay/home')
}

/** A person at a chart point, by the person's UUID, as the web's `urls.personByUUID` builds it. */
export function personWebUrl(scope: ProjectScope | null, personId: string): string | undefined {
    return scope ? `${scope.host}/project/${scope.projectId}/persons/${encodeURIComponent(personId)}` : undefined
}
