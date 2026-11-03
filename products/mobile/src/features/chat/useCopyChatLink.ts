import * as Clipboard from 'expo-clipboard'
import { useRef, useState } from 'react'

import { type AnalyticsProperties, actionTracker } from '@/lib/analytics'

interface CopyChatLink {
    copyLink: (url: string | undefined, properties?: AnalyticsProperties) => Promise<boolean>
    copying: boolean
}

export function useCopyChatLink(showNotice: (message: string) => void): CopyChatLink {
    const pending = useRef(false)
    const [copying, setCopying] = useState(false)

    const copyLink = async (url: string | undefined, properties?: AnalyticsProperties): Promise<boolean> => {
        if (!url || pending.current) {
            return false
        }
        pending.current = true
        setCopying(true)
        const record = actionTracker(properties)
        try {
            const copied = await Clipboard.setStringAsync(url)
            record(copied ? 'mobile_chat_link_copied' : 'mobile_chat_link_copy_failed')
            showNotice(copied ? 'Chat link copied' : "Couldn't copy the link. Try again.")
            return copied
        } catch {
            record('mobile_chat_link_copy_failed')
            showNotice("Couldn't copy the link. Try again.")
            return false
        } finally {
            pending.current = false
            setCopying(false)
        }
    }

    return { copyLink, copying }
}
