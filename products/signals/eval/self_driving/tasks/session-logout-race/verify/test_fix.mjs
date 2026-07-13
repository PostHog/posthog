// Catches: an in-flight refreshUser() resolving after logout() and re-populating the signed-out session store with the stale user.
import assert from 'node:assert/strict'
import test from 'node:test'

import { getUser, isAuthenticated, login, logout, refreshUser } from '../src/state/session.js'

function jsonResponse(body) {
  return { ok: true, status: 200, json: async () => body }
}

test('a refresh that resolves after logout does not restore the user', async () => {
  let resolveMe = null
  globalThis.fetch = async (url) => {
    const path = String(url)
    if (path.endsWith('/api/login')) {
      return jsonResponse({ token: 'tok_1', user: { id: 'u1', email: 'dana@acme.test', name: 'Dana' } })
    }
    if (path.endsWith('/api/me')) {
      return new Promise((resolve) => {
        resolveMe = resolve
      })
    }
    throw new Error(`unexpected fetch: ${path}`)
  }

  await login('dana@acme.test', 'hunter2')
  assert.ok(isAuthenticated(), 'precondition: login signs the user in')

  const pending = refreshUser() // in-flight refresh, e.g. the 60s interval tick
  assert.ok(resolveMe, 'precondition: refresh request is in flight')

  logout()
  assert.equal(getUser(), null, 'logout clears the user immediately')

  resolveMe(jsonResponse({ id: 'u1', email: 'dana@acme.test', name: 'Dana' }))
  await pending.catch(() => {}) // a fixed implementation may resolve empty or reject - both are fine

  assert.equal(getUser(), null, 'stale refresh must not restore the signed-out user')
  assert.equal(isAuthenticated(), false, 'session must stay signed out after the stale refresh settles')
})
