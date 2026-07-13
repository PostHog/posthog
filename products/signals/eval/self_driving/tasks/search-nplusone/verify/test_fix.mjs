// Catches: searchDirectory fetching each result's owner profile one store call at a time (N+1) instead of batching the lookups.
import assert from 'node:assert/strict'
import test from 'node:test'

import { searchDirectory } from '../src/search.js'

function makeFixtures(listingCount) {
  const profiles = new Map()
  const listings = []
  for (let i = 1; i <= listingCount; i++) {
    const ownerId = `p${String(((i - 1) % 30) + 1).padStart(2, '0')}`
    if (!profiles.has(ownerId)) {
      profiles.set(ownerId, { id: ownerId, name: `Owner ${ownerId}`, rating: 4.5, responseTimeHours: 4 })
    }
    listings.push({
      id: `l${String(i).padStart(2, '0')}`,
      title: `Emergency plumber ${i}`,
      category: 'plumbing',
      city: 'Portland',
      ownerId,
      description: 'Pipes, leaks, water heaters.',
    })
  }
  return { listings, profiles }
}

class CountingStore {
  constructor({ listings, profiles }) {
    this.listings = listings
    this.profiles = profiles
    this.calls = 0
  }

  async searchListings() {
    this.calls += 1
    return this.listings.slice()
  }

  async getListing(id) {
    this.calls += 1
    return this.listings.find((listing) => listing.id === id) ?? null
  }

  async getProfile(id) {
    this.calls += 1
    return this.profiles.get(id) ?? null
  }

  async getProfilesByIds(ids) {
    this.calls += 1
    const unique = [...new Set(ids)]
    return unique.map((id) => this.profiles.get(id)).filter(Boolean)
  }
}

test('search over 50 results uses a bounded number of store calls', async () => {
  const store = new CountingStore(makeFixtures(50))
  const results = await searchDirectory(store, 'plumber')
  assert.equal(results.length, 50)
  for (const result of results) {
    assert.ok(result.owner, `result ${result.id} is missing its owner profile`)
    assert.equal(result.owner.id, result.ownerId)
    assert.equal(result.owner.name, `Owner ${result.ownerId}`)
  }
  assert.ok(
    store.calls <= 3,
    `expected at most 3 store calls for a 50-result search (batched owner lookup), saw ${store.calls}`
  )
})
