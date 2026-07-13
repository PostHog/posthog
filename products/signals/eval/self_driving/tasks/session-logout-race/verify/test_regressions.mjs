// Catches: a race fix that breaks the normal session lifecycle - login, uninterrupted refresh, logout, re-login, and refresh after re-login.
// The session store is module-level state, so the lifecycle is exercised as one sequential test.
import assert from 'node:assert/strict'
import test from 'node:test'

import { getUser, isAuthenticated, login, logout, refreshUser } from '../src/state/session.js'

function jsonResponse(body) {
  return { ok: true, status: 200, json: async () => body }
}

function stubApi({ me }) {
  globalThis.fetch = async (url, options = {}) => {
    const path = String(url)
    if (path.endsWith('/api/login')) {
      const { email } = JSON.parse(options.body)
      return jsonResponse({ token: `tok_${email}`, user: { id: 'u1', email, name: 'Dana', plan: 'free' } })
    }
    if (path.endsWith('/api/me')) {
      return jsonResponse(me)
    }
    throw new Error(`unexpected fetch: ${path}`)
  }
}

test('normal session lifecycle keeps working', async () => {
  // Login signs the user in.
  stubApi({ me: { id: 'u1', email: 'dana@acme.test', name: 'Dana', plan: 'free' } })
  const user = await login('dana@acme.test', 'hunter2')
  assert.equal(user.email, 'dana@acme.test')
  assert.equal(getUser().email, 'dana@acme.test')
  assert.ok(isAuthenticated())

  // An uninterrupted refresh applies updated user data.
  stubApi({ me: { id: 'u1', email: 'dana@acme.test', name: 'Dana', plan: 'scale' } })
  await refreshUser()
  assert.equal(getUser().plan, 'scale')
  assert.ok(isAuthenticated())

  // Logout clears the session.
  logout()
  assert.equal(getUser(), null)
  assert.equal(isAuthenticated(), false)

  // Logging in again after logout works (a permanent "ignore all writes" fix would break this).
  await login('dana@acme.test', 'hunter2')
  assert.ok(isAuthenticated())
  assert.equal(getUser().email, 'dana@acme.test')

  // A refresh started after re-login still applies.
  stubApi({ me: { id: 'u1', email: 'dana@acme.test', name: 'Dana Q.', plan: 'scale' } })
  await refreshUser()
  assert.equal(getUser().name, 'Dana Q.')
  assert.ok(isAuthenticated())
})
