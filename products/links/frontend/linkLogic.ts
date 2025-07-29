import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { deleteFromTree } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import type { LinkType } from '~/types'
import { Breadcrumb, ProjectTreeRef } from '~/types'

import type { linkLogicType } from './linkLogicType'
import { linksLogic } from './linksLogic'

export type AvailableDomain = 'phog.gg' | 'postho.gg' | 'hog.gg' | 'custom'
export type DomainDefinition = {
    label: string
    value: AvailableDomain
    soon?: boolean
    paid?: boolean
}

export const AVAILABLE_DOMAINS: DomainDefinition[] = [
    { label: 'phog.gg', value: 'phog.gg' },
    { label: 'postho.gg', value: 'postho.gg', soon: true },
    { label: 'hog.gg', value: 'hog.gg', soon: true },
    { label: 'Custom (BYOD)', value: 'custom', soon: true, paid: true },
]

export const DEFAULT_SHORT_LINK_DOMAIN = 'phog.gg'
export const NEW_LINK: Partial<LinkType> = {
    id: 'new',
    short_link_domain: DEFAULT_SHORT_LINK_DOMAIN,
    short_code: '',
    redirect_url: '',
    description: '',
}

export interface LinkLogicProps {
    /** Either a UUID or "new". */
    id: string
}

export const linkLogic = kea<linkLogicType>([
    path(['products', 'links', 'frontend', 'linkLogic']),
    props({} as LinkLogicProps),
    key(({ id }) => id),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], linksLogic, ['links']],
        actions: [linksLogic, ['loadLinks', 'loadLinksSuccess']],
    })),
    actions({
        setLinkMissing: true,
        editLink: (editing: boolean) => ({ editing }),
        deleteLink: (linkId: LinkType['id']) => ({ linkId }),
    }),
    loaders(({ props, actions }) => ({
        link: {
            loadLink: async () => {
                if (props.id && props.id !== 'new') {
                    try {
                        const response = await api.links.get(props.id)
                        return response
                    } catch (error) {
                        actions.setLinkMissing()
                        throw error
                    }
                }

                return NEW_LINK as LinkType
            },
            saveLink: async (updatedLink: Partial<LinkType>) => {
                const result: LinkType = await (props.id === 'new'
                    ? api.links.create(updatedLink)
                    : api.links.update(props.id, updatedLink))
                if (props.id === 'new') {
                    router.actions.replace(urls.link(result.id))
                }

                return result
            },
        },
    })),
    forms(({ actions, props }) => ({
        link: {
            defaults: { ...NEW_LINK } as LinkType,
            errors: (payload) => ({
                redirect_url: !payload?.redirect_url ? 'Must include a destination url' : undefined,
                short_code: !payload?.short_code ? 'Must include a short code' : undefined,
            }),
            submit: async (payload) => {
                if (props.id && props.id !== 'new') {
                    actions.saveLink(payload)
                } else {
                    actions.saveLink({ ...payload, _create_in_folder: 'Unfiled/Links' })
                }
            },
        },
    })),
    reducers({
        linkMissing: [false, { setLinkMissing: () => true }],
        isEditingLink: [false, { editLink: (_, { editing }) => editing }],
    }),
    selectors({
        mode: [(_, p) => [p.id], (id): 'view' | 'edit' => (id === 'new' ? 'edit' : 'view')],
        breadcrumbs: [
            (s) => [s.link],
            (link: LinkType): Breadcrumb[] => [
                {
                    key: 'Link',
                    name: 'Link Management',
                    path: urls.links(),
                },
                {
                    key: ['Link', link.id || 'new'],
                    name: `${link.short_code} (${link.redirect_url})`,
                },
            ],
        ],
        projectTreeRef: [
            () => [(_, props: LinkLogicProps) => props.id],
            (id): ProjectTreeRef => ({ type: 'link', ref: id === 'new' ? null : String(id) }),
        ],
    }),
    listeners(({ actions, values }) => ({
        saveLinkSuccess: ({ link }) => {
            lemonToast.success('Link saved')
            actions.loadLinks()
            link.id && router.actions.replace(urls.link(link.id))
            actions.editLink(false)
        },
        deleteLink: async ({ linkId }) => {
            try {
                await api.links.delete(linkId)
                lemonToast.info('Link deleted. Existing `$linkclick` events will be kept for future analysis')
                actions.loadLinksSuccess(values.links.filter((link) => link.id !== linkId))
                deleteFromTree('link', linkId)
                router.actions.push(urls.links())
            } catch (e) {
                lemonToast.error(`Error deleting Link: ${e}`)
            }
        },
    })),
    urlToAction(({ actions, props }) => ({
        [urls.link(props.id ?? 'new')]: (_, __, ___, { method }) => {
            // If the URL was pushed (user clicked on a link), reset the scene's data.
            // This avoids resetting form fields if you click back/forward.
            if (method === 'PUSH') {
                if (props.id) {
                    actions.loadLink()
                }
            }
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.id !== 'new') {
            actions.loadLink()
        }
    }),
])
