import { runDigest } from './digest.js'

export function startScheduler(deps, intervalMs) {
  const timer = setInterval(() => {
    runDigest(deps).catch((error) => {
      console.error('[scheduler] digest run failed', error)
    })
  }, intervalMs)
  timer.unref?.()
  return timer
}
