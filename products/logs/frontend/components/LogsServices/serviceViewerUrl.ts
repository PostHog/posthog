import { combineUrl } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

/** Viewer tab scoped to one service. logsSceneLogic reads `serviceNames` back off the URL. */
export function serviceViewerUrl(serviceName: string): string {
    return combineUrl(urls.currentProject(urls.logs()), {
        activeTab: 'viewer',
        serviceNames: serviceName,
    }).url
}

export function copyServiceDeepLink(serviceName: string): void {
    const full = urls.absolute(serviceViewerUrl(serviceName))
    void navigator.clipboard.writeText(full).then(
        () => lemonToast.success('Link copied'),
        () => lemonToast.error('Could not copy link')
    )
}
