import { urls } from 'scenes/urls'

export const emailDomainPageUrl = (teamId: number, integrationId: number): string =>
    `${window.location.origin}/project/${teamId}${urls.workflowsEmailDomain(integrationId)}`
