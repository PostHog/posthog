export const STREAMLIT_APP_STATUSES = ['starting', 'running', 'stopping', 'stopped', 'error'] as const

export type StreamlitAppStatus = (typeof STREAMLIT_APP_STATUSES)[number]

// The API types status as a free-form string. Unrecognized values fall back to stopped so
// the UI never renders a running app it can't actually reach.
export function toStreamlitAppStatus(status: string | undefined): StreamlitAppStatus {
    return STREAMLIT_APP_STATUSES.includes(status as StreamlitAppStatus) ? (status as StreamlitAppStatus) : 'stopped'
}
