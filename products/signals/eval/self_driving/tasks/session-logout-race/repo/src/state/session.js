import { clearToken, fetchCurrentUser, loginRequest, setToken } from '../api/client.js'
import { capture } from '../analytics.js'

const state = {
  user: null,
  status: 'signed-out',
}

export function getUser() {
  return state.user
}

export function isAuthenticated() {
  return state.status === 'signed-in' && state.user !== null
}

export async function login(email, password) {
  const { token, user } = await loginRequest(email, password)
  setToken(token)
  state.user = user
  state.status = 'signed-in'
  capture(user.id, 'user_logged_in', {})
  return user
}

export async function refreshUser() {
  const user = await fetchCurrentUser()
  state.user = user
  state.status = 'signed-in'
  capture(user.id, 'session_refreshed', {})
  return user
}

export function logout() {
  const user = state.user
  clearToken()
  state.user = null
  state.status = 'signed-out'
  if (user) {
    capture(user.id, 'user_logged_out', {})
  }
}
