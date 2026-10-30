import * as Updates from 'expo-updates'
import { useEffect, useRef, useState } from 'react'
import { AppState, Keyboard, Platform } from 'react-native'

import { queryClient } from '@/api/queryClient'
import { captureError } from '@/lib/analytics'
import { isAppReloadBlocked } from '@/lib/appReload'
import { toError } from '@/lib/errors'

import { AutomaticUpdates } from './automaticUpdates'

const FOREGROUND_SETTLE_MS = 1000
const UPDATE_POLL_INTERVAL_MS = 60 * 1000

export function useAutomaticUpdates(canReload: boolean): void {
    const state = Updates.useUpdates()
    const latest = useRef({ state, canReload })
    latest.current = { state, canReload }
    const [updates] = useState(() => new AutomaticUpdates(Updates))
    const startupRunning = state.isStartupProcedureRunning

    useEffect(() => {
        if (__DEV__ || Platform.OS === 'web' || !Updates.isEnabled || startupRunning) {
            return
        }
        const onError = (error: unknown): void => captureError(toError(error))
        const check = (): void => {
            if (AppState.currentState === 'active' || AppState.currentState === null) {
                void updates.check(latest.current.state).catch(onError)
            }
        }
        let foregroundTimer: ReturnType<typeof setTimeout> | undefined
        check()
        if (AppState.currentState === 'background') {
            updates.background()
        }
        const subscription = AppState.addEventListener('change', (next) => {
            clearTimeout(foregroundTimer)
            if (next === 'background') {
                updates.background()
            } else if (next === 'active') {
                foregroundTimer = setTimeout(() => {
                    if (AppState.currentState !== 'active') {
                        return
                    }
                    void updates
                        .foreground(
                            latest.current.state,
                            latest.current.canReload &&
                                !Keyboard.isVisible() &&
                                !isAppReloadBlocked() &&
                                queryClient.isMutating() === 0
                        )
                        .catch(onError)
                }, FOREGROUND_SETTLE_MS)
            }
        })
        const timer = setInterval(check, UPDATE_POLL_INTERVAL_MS)
        return () => {
            subscription.remove()
            clearInterval(timer)
            clearTimeout(foregroundTimer)
        }
    }, [updates, startupRunning])
}
