const API_BASE = ''

let token = null

export function setToken(next) {
  token = next
}

export function clearToken() {
  token = null
}

export function getToken() {
  return token
}

async function request(path, options = {}) {
  const headers = {
    'content-type': 'application/json',
    ...(token ? { authorization: `Bearer ${token}` } : {}),
  }
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!response.ok) {
    throw new Error(`Request to ${path} failed: ${response.status}`)
  }
  return response.json()
}

export async function loginRequest(email, password) {
  return request('/api/login', { method: 'POST', body: JSON.stringify({ email, password }) })
}

export async function fetchCurrentUser() {
  return request('/api/me')
}
