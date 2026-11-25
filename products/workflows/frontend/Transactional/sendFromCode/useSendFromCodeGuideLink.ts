import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect, useRef } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { transactionalEmailsLogic } from '../transactionalEmailsLogic'
import { SEND_FROM_CODE_GUIDE_PARAM, SEND_FROM_CODE_GUIDE_VALUE } from './sendFromCodeGuideUrl'

interface GuideLinkInputs {
    flagsReceived: boolean
    sendFromCodeEnabled: boolean
    templatesLoading: boolean
    templatesFailed: boolean
    codeEmails: CodeEmailApi[] | null
}

function guideLinkState({
    flagsReceived,
    sendFromCodeEnabled,
    templatesLoading,
    templatesFailed,
    codeEmails,
}: GuideLinkInputs): { settled: boolean; offered: boolean } {
    const listSettled = !templatesLoading && (templatesFailed || codeEmails !== null)
    return {
        settled: flagsReceived && (!sendFromCodeEnabled || listSettled),
        offered: sendFromCodeEnabled && listSettled && !templatesFailed && codeEmails?.length === 0,
    }
}

export function useSendFromCodeGuideLink(openGuide: () => void): void {
    const { hasNoEmails, codeEmails, transactionalTemplatesLoading, transactionalTemplatesFailed } =
        useValues(transactionalEmailsLogic)
    const { receivedFeatureFlags } = useValues(featureFlagLogic)
    const sendFromCodeEnabled = useFeatureFlag('WORKFLOWS_EMAIL_FROM_CODE')
    const { searchParams } = useValues(router)
    const linked = searchParams[SEND_FROM_CODE_GUIDE_PARAM] === SEND_FROM_CODE_GUIDE_VALUE
    const { settled, offered } = guideLinkState({
        flagsReceived: receivedFeatureFlags,
        sendFromCodeEnabled,
        templatesLoading: transactionalTemplatesLoading,
        templatesFailed: transactionalTemplatesFailed,
        codeEmails,
    })
    const openGuideRef = useRef(openGuide)
    openGuideRef.current = openGuide

    useEffect(() => {
        if (!linked || !settled) {
            return
        }
        if (offered) {
            // pinned: analytics event name
            posthog.capture('send from code guide opened', {
                surface: hasNoEmails ? 'transactional_empty' : 'transactional',
                entry: 'domain_ready',
            })
            if (!hasNoEmails) {
                openGuideRef.current()
            }
        }
        const { [SEND_FROM_CODE_GUIDE_PARAM]: _guide, ...otherParams } = router.values.searchParams
        router.actions.replace(router.values.location.pathname, otherParams, router.values.hashParams)
    }, [linked, settled, offered, hasNoEmails])
}
