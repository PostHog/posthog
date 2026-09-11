import { useAsyncActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import {
    AuthorizedUrlListType,
    authorizedUrlListLogic,
    defaultAuthorizedUrlProperties,
    sanitizePossibleWildCardedURL,
    validateProposedUrl,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'

const HOST_WILDCARD_REGEX = /^https?:\/\/[^/]*\*/

function deriveAuthorizationCandidate(dataUrl: string): string | null {
    if (HOST_WILDCARD_REGEX.test(dataUrl)) {
        const match = dataUrl.match(/^(https?:\/\/[^/]+)/)
        return match ? match[1] : null
    }
    try {
        return sanitizePossibleWildCardedURL(dataUrl).origin
    } catch {
        return null
    }
}

function authorizationDisabledReason(): string | null {
    if (inStorybook() || inStorybookTestRunner()) {
        return null
    }
    return getAccessControlDisabledReason(
        AccessControlResourceType.WebAnalytics,
        AccessControlLevel.Editor,
        undefined,
        false
    )
}

export function HeatmapsForbiddenURL(): JSX.Element {
    const { dataUrl } = useValues(heatmapsBrowserLogic)
    const { currentTeamLoading } = useValues(teamLogic)
    const logic = authorizedUrlListLogic({
        ...defaultAuthorizedUrlProperties,
        type: AuthorizedUrlListType.TOOLBAR_URLS,
    })
    const { authorizedUrls } = useValues(logic)
    const { addUrl } = useAsyncActions(logic)

    const { urlToAuthorize, validationError } = useMemo(() => {
        if (!dataUrl) {
            return { urlToAuthorize: null, validationError: null }
        }
        const candidate = deriveAuthorizationCandidate(dataUrl)
        if (!candidate) {
            return { urlToAuthorize: null, validationError: 'Enter a valid URL to authorize' }
        }
        const error = validateProposedUrl(candidate, authorizedUrls, false, true)
        return { urlToAuthorize: candidate, validationError: error ?? null }
    }, [dataUrl, authorizedUrls])

    const disabledReason = authorizationDisabledReason()

    return (
        <div className="my-2">
            <LemonBanner
                type="error"
                action={
                    urlToAuthorize && !validationError
                        ? {
                              children: 'Authorize URL',
                              icon: <IconPlus />,
                              loading: currentTeamLoading,
                              disabledReason,
                              onClick: async () => {
                                  await addUrl(urlToAuthorize)
                                  // The save can be rejected, so only claim success once the URL
                                  // is really on the project's authorized list.
                                  if (logic.values.authorizedUrls.includes(urlToAuthorize)) {
                                      lemonToast.success(`Authorized ${urlToAuthorize}`)
                                  }
                              },
                              'data-attr': 'heatmaps-authorize-url',
                          }
                        : undefined
                }
            >
                {dataUrl} is not an authorized URL.
                {validationError ? <> {validationError}.</> : null}
                {disabledReason ? <> Ask a web analytics editor to authorize it.</> : null}
            </LemonBanner>
        </div>
    )
}
