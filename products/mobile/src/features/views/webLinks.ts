import type { ProjectScope } from '@/api/reports'

// Links that hand off to the web. Shortcut hrefs carry no project prefix, so the project goes in front.

/** The web page of a view, from its shortcut `href` such as `/dashboard/12`. Undefined without a project (demo). */
export function viewWebUrl(scope: ProjectScope | null, href: string | null): string | undefined {
    if (!scope || !href) {
        return undefined
    }
    return `${scope.host}/project/${scope.projectId}${href.startsWith('/') ? href : `/${href}`}`
}

/** Browse's Recordings row. */
export function recordingsWebUrl(scope: ProjectScope | null): string | undefined {
    return scope ? `${scope.host}/project/${scope.projectId}/replay/home` : undefined
}

/** "Watch recordings" on one session. */
export function recordingWebUrl(scope: ProjectScope | null, sessionId: string): string | undefined {
    return scope ? `${scope.host}/project/${scope.projectId}/replay/${encodeURIComponent(sessionId)}` : undefined
}

/** A person at a chart point, by the person's UUID, as the web's `urls.personByUUID` builds it. */
export function personWebUrl(scope: ProjectScope | null, personId: string): string | undefined {
    return scope ? `${scope.host}/project/${scope.projectId}/persons/${encodeURIComponent(personId)}` : undefined
}
