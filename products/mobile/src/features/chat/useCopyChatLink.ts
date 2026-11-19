import * as Clipboard from 'expo-clipboard'
import { useRef, useState } from 'react'

interface CopyChatLink {
    copyLink: (url: string | undefined) => Promise<boolean>
    copying: boolean
}

export function useCopyChatLink(showNotice: (message: string) => void): CopyChatLink {
    const pending = useRef(false)
    const [copying, setCopying] = useState(false)

    const copyLink = async (url: string | undefined): Promise<boolean> => {
        if (!url || pending.current) {
            return false
        }
        pending.current = true
        setCopying(true)
        try {
            const copied = await Clipboard.setStringAsync(url)
            showNotice(copied ? 'Chat link copied' : "Couldn't copy the link. Try again.")
            return copied
        } catch {
            showNotice("Couldn't copy the link. Try again.")
            return false
        } finally {
            pending.current = false
            setCopying(false)
        }
    }

    return { copyLink, copying }
}
