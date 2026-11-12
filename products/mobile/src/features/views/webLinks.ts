import type { ProjectScope } from '@/api/reports'
import type { NavPin } from '@/features/tabs/navPinStore'

// Links that hand off to the web. Shortcut hrefs carry no project prefix, so the project goes in front.

/** The web page of a view, from its shortcut `href` such as `/dashboard/12`. Undefined without a project (demo). */
export function viewWebUrl(scope: ProjectScope | null, href: string | null): string | undefined {
    if (!scope || !href) {
        return undefined
    }
    return `${scope.host}/project/${scope.projectId}${href.startsWith('/') ? href : `/${href}`}`
}

const NAV_LIST_PATHS: Record<NavPin, string> = {
    errors: '/error_tracking',
    replay: '/replay/home',
    web_analytics: '/web',
    live: '/web/live',
    experiments: '/experiments',
}

/** The web page of a list that can sit in the navigation. */
export function navListWebUrl(scope: ProjectScope | null, list: NavPin): string | undefined {
    return viewWebUrl(scope, NAV_LIST_PATHS[list])
}

/** A person at a chart point, by the person's UUID, as the web's `urls.personByUUID` builds it. */
export function personWebUrl(scope: ProjectScope | null, personId: string): string | undefined {
    return scope ? `${scope.host}/project/${scope.projectId}/persons/${encodeURIComponent(personId)}` : undefined
}
