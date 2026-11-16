import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect, useRef } from 'react'

import { SEND_FROM_CODE_GUIDE_PARAM, SEND_FROM_CODE_GUIDE_VALUE } from './sendFromCodeGuideUrl'

export function useSendFromCodeGuideLink({
    surface,
    settled,
    offered,
    onOpen,
}: {
    surface: 'transactional' | 'transactional_empty'
    settled: boolean
    offered: boolean
    onOpen?: () => void
}): void {
    const { searchParams } = useValues(router)
    const linked = searchParams[SEND_FROM_CODE_GUIDE_PARAM] === SEND_FROM_CODE_GUIDE_VALUE
    const onOpenRef = useRef(onOpen)
    onOpenRef.current = onOpen

    useEffect(() => {
        if (!linked || !settled) {
            return
        }
        if (offered) {
            // pinned: analytics event name
            posthog.capture('send from code guide opened', { surface, entry: 'domain_ready' })
            onOpenRef.current?.()
        }
        const { [SEND_FROM_CODE_GUIDE_PARAM]: _guide, ...otherParams } = router.values.searchParams
        router.actions.replace(router.values.location.pathname, otherParams, router.values.hashParams)
    }, [linked, settled, offered, surface])
}
