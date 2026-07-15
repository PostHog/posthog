/**
 * The shell UI: region selection, sign-in, and account management. Everything
 * here works offline except the sign-in verification itself.
 */

import type { CloudRegion, DesktopApi, DesktopState } from '../shared/ipc.ts'

declare global {
    interface Window {
        posthogDesktop: DesktopApi
    }
}

const desktop = window.posthogDesktop

function el<T extends HTMLElement>(id: string): T {
    const node = document.getElementById(id)
    if (!node) {
        throw new Error(`Missing element #${id}`)
    }
    return node as T
}

const signinCard = el<HTMLElement>('signin-card')
const signedinCard = el<HTMLElement>('signedin-card')
const regionsContainer = el<HTMLElement>('regions')
const customHostInput = el<HTMLInputElement>('custom-host')
const apiKeyInput = el<HTMLInputElement>('api-key')
const signInButton = el<HTMLButtonElement>('sign-in')
const errorText = el<HTMLElement>('error')
const statusText = el<HTMLElement>('status')
const frontendWarning = el<HTMLElement>('frontend-warning')

let selectedRegion: CloudRegion = 'us'
let signingIn = false

function setRegion(region: CloudRegion): void {
    selectedRegion = region
    for (const button of regionsContainer.querySelectorAll<HTMLButtonElement>('.Shell__region')) {
        button.classList.toggle('Shell__region--active', button.dataset.region === region)
    }
    customHostInput.classList.toggle('Shell--hidden', region !== 'custom')
}

function showError(message: string): void {
    errorText.textContent = message
    errorText.classList.toggle('Shell__error--visible', message.length > 0)
}

function render(state: DesktopState): void {
    frontendWarning.classList.toggle('Shell__warning--visible', !state.frontendBuilt)
    signinCard.style.display = state.signedIn ? 'none' : 'block'
    signedinCard.style.display = state.signedIn ? 'block' : 'none'
    if (state.signedIn) {
        el<HTMLElement>('account-email').textContent = state.signedInEmail || 'unknown'
        el<HTMLElement>('account-host').textContent = state.apiHost ? `on ${state.apiHost}` : ''
        el<HTMLButtonElement>('open-app').disabled = !state.frontendBuilt
    } else {
        setRegion(state.settings.region)
        customHostInput.value = state.settings.customHost
    }
    statusText.textContent = `PostHog desktop ${state.version} · settings are stored on this device`
}

regionsContainer.addEventListener('click', (event) => {
    const target = (event.target as HTMLElement).closest<HTMLButtonElement>('.Shell__region')
    if (target?.dataset.region) {
        setRegion(target.dataset.region as CloudRegion)
        showError('')
        void desktop.updateSettings({ region: selectedRegion })
    }
})

el<HTMLButtonElement>('open-key-settings').addEventListener('click', () => {
    const host =
        selectedRegion === 'custom'
            ? customHostInput.value.trim() || 'https://us.posthog.com'
            : `https://${selectedRegion}.posthog.com`
    void desktop.openExternal(`${host.replace(/\/$/, '')}/settings/user-api-keys`)
})

async function signIn(): Promise<void> {
    if (signingIn) {
        return
    }
    signingIn = true
    signInButton.disabled = true
    signInButton.textContent = 'Signing in...'
    showError('')
    try {
        const result = await desktop.signIn({
            region: selectedRegion,
            customHost: customHostInput.value,
            apiKey: apiKeyInput.value,
        })
        if (result.ok) {
            apiKeyInput.value = ''
            const state = await desktop.getState()
            render(state)
            if (state.frontendBuilt) {
                void desktop.openApp()
            }
        } else {
            showError(result.error)
        }
    } finally {
        signingIn = false
        signInButton.disabled = false
        signInButton.textContent = 'Sign in'
    }
}

signInButton.addEventListener('click', () => void signIn())
apiKeyInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
        void signIn()
    }
})

el<HTMLButtonElement>('open-app').addEventListener('click', () => void desktop.openApp())
el<HTMLButtonElement>('sign-out').addEventListener('click', async () => {
    await desktop.signOut()
    render(await desktop.getState())
})

void desktop.getState().then(render)
