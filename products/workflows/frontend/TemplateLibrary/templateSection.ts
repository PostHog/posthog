import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

/** The nav section a template page belongs to, read from the URL it was opened under. */
export type TemplateSection = 'transactional' | 'broadcasts' | 'workflows'

export function templateSectionFor(pathname: string): TemplateSection {
    const path = removeProjectIdIfPresent(pathname)
    if (path.startsWith('/transactional/')) {
        return 'transactional'
    }
    if (path.startsWith('/broadcasts/')) {
        return 'broadcasts'
    }
    return 'workflows'
}

/** A template's page in the given section, so opening it keeps the nav and back links in place. */
export function templateUrlInSection(id: string, section: TemplateSection): string {
    if (section === 'transactional') {
        return urls.transactionalTemplate(id)
    }
    if (section === 'broadcasts') {
        return urls.broadcastsTemplate(id)
    }
    return urls.workflowsLibraryTemplate(id)
}

/** The Templates tab a template page returns to. */
export function templateLibraryUrl(section: TemplateSection): string {
    if (section === 'transactional') {
        return urls.transactional('library')
    }
    if (section === 'broadcasts') {
        return urls.broadcasts('library')
    }
    return urls.workflows('library')
}
