import { initAnalytics } from '../analytics.js'
import { refreshUser } from '../state/session.js'
import { renderHeader } from './header.js'

const REFRESH_INTERVAL_MS = 60_000

function render() {
  const header = document.getElementById('app-header')
  if (header) {
    renderHeader(header)
  }
}

async function boot() {
  initAnalytics({ apiKey: window.ACME_POSTHOG_KEY })
  try {
    await refreshUser()
  } catch {
    // Not signed in yet - the header renders the sign-in link.
  }
  render()
  // Keep plan changes and renames fresh without a reload.
  setInterval(() => {
    refreshUser().then(render, () => {})
  }, REFRESH_INTERVAL_MS)
}

boot()
