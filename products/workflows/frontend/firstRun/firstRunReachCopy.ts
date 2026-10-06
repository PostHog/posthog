import { pluralize } from 'lib/utils/strings'

import type { FirstRunReach } from './firstRunReachLogic'

function reachedMembers({ counts }: FirstRunReach): string {
    return counts
        ? `your organization's ${pluralize(counts.reached, 'verified member')}`
        : 'verified members of your organization'
}

function peopleNotReachedYet({ counts }: FirstRunReach): string {
    return counts
        ? `the ${pluralize(counts.notReachedYet, 'person', 'people')} in this project with an email address`
        : 'the people in this project'
}

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1)
}

function notReachedYetCopy(reach: FirstRunReach): string {
    const domainNotVerified = reach.ownDomain === 'verifying' ? 'Your domain is not verified yet. ' : ''
    if (reach.counts?.notReachedYet === 0) {
        return `${domainNotVerified}No one in this project has an email address yet.`
    }
    return reach.ownDomain === 'verifying'
        ? `${domainNotVerified}Once it is, ${peopleNotReachedYet(reach)} can get these emails too.`
        : `${capitalize(peopleNotReachedYet(reach))} can get these emails once you send from your own domain.`
}

export function firstRunReachCopy(reach: FirstRunReach): string {
    return `only to ${reachedMembers(reach)}. ${notReachedYetCopy(reach)}`
}
