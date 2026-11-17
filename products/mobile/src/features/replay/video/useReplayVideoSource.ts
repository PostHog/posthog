import type { VideoPlayer } from 'expo-video'
import { useEffect } from 'react'
import { AppState } from 'react-native'

import { ApiError } from '@/api/client'
import { isTransientReplayVideoError, type ReplayVideoSource, resolveReplayVideoSource } from '@/api/replayVideo'
import { sessionGeneration } from '@/auth/tokens'

const RENEW_BEFORE_EXPIRY_MS = 60_000
const RENEW_RETRY_MS = 10_000

export function useReplayVideoSource(
    player: VideoPlayer,
    exportId: number,
    source: ReplayVideoSource,
    onError: (currentTime: number) => void
): void {
    useEffect(() => {
        const controller = new AbortController()
        const generation = sessionGeneration()
        let expiresAt = source.expiresAt
        let timer: ReturnType<typeof setTimeout> | undefined
        let renewing = false
        const isCurrent = (): boolean => !controller.signal.aborted && sessionGeneration() === generation
        const needsRenewal = (): boolean => expiresAt !== undefined && Date.now() >= expiresAt - RENEW_BEFORE_EXPIRY_MS

        const scheduleRenewal = (): void => {
            if (expiresAt !== undefined) {
                timer = setTimeout(() => void renew(), Math.max(0, expiresAt - Date.now() - RENEW_BEFORE_EXPIRY_MS))
            }
        }

        const renew = async (): Promise<void> => {
            if (renewing || !isCurrent()) {
                return
            }
            renewing = true
            clearTimeout(timer)
            let currentTime: number | undefined
            try {
                const fresh = await resolveReplayVideoSource(exportId, controller.signal)
                if (!isCurrent()) {
                    return
                }
                currentTime = player.currentTime
                const playing = player.playing
                const playbackRate = player.playbackRate
                await player.replaceAsync(fresh)
                if (!isCurrent()) {
                    return
                }
                player.currentTime = currentTime
                player.playbackRate = playbackRate
                if (playing) {
                    player.play()
                } else {
                    player.pause()
                }
                if (player.status === 'error') {
                    onError(currentTime)
                    return
                }
                expiresAt = fresh.expiresAt
                scheduleRenewal()
            } catch (error) {
                if (isCurrent()) {
                    if (isTransientReplayVideoError(error) && player.status !== 'error') {
                        const retryAfter = error instanceof ApiError ? (error.retryAfterSeconds ?? 0) * 1000 : 0
                        timer = setTimeout(() => void renew(), Math.max(RENEW_RETRY_MS, retryAfter))
                    } else {
                        onError(currentTime ?? player.currentTime)
                    }
                }
            } finally {
                renewing = false
            }
        }

        const checkStatus = (status: VideoPlayer['status']): void => {
            if (status === 'error' && !renewing && isCurrent()) {
                if (needsRenewal()) {
                    void renew()
                } else {
                    onError(player.currentTime)
                }
            }
        }
        const statusSubscription = player.addListener('statusChange', ({ status }) => checkStatus(status))
        // Native loading can finish before effects subscribe, and backgrounded apps can miss the renewal timer.
        checkStatus(player.status)
        scheduleRenewal()
        const appSubscription = AppState.addEventListener('change', (next) => {
            if (next === 'active' && needsRenewal()) {
                void renew()
            }
        })
        return () => {
            controller.abort()
            clearTimeout(timer)
            statusSubscription.remove()
            appSubscription.remove()
        }
    }, [player, exportId, source, onError])
}
