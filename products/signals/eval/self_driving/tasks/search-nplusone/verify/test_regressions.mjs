// Catches: a search fix that breaks result correctness - owner attachment, ranking order, result limit, or missing-profile handling.
import assert from 'node:assert/strict'
import test from 'node:test'

import { searchDirectory } from '../src/search.js'

class FakeStore {
  constructor(listings, profiles) {
    this.listings = listings
    this.profiles = new Map(profiles.map((profile) => [profile.id, profile]))
  }

  async searchListings() {
    return this.listings.slice()
  }

  async getListing(id) {
    return this.listings.find((listing) => listing.id === id) ?? null
  }

  async getProfile(id) {
    return this.profiles.get(id) ?? null
  }

  async getProfilesByIds(ids) {
    const unique = [...new Set(ids)]
    return unique.map((id) => this.profiles.get(id)).filter(Boolean)
  }
}

const LISTINGS = [
  {
    id: 'l01',
    title: 'Emergency plumber on call',
    category: 'plumbing',
    city: 'Portland',
    ownerId: 'p01',
    description: 'Burst pipes and leaks.',
  },
  {
    id: 'l02',
    title: 'Plumber pros - emergency plumber team',
    category: 'plumber services',
    city: 'Portland',
    ownerId: 'p02',
    description: 'A plumber for every job.',
  },
  {
    id: 'l03',
    title: 'Panel upgrades',
    category: 'electrical',
    city: 'Salem',
    ownerId: 'p03',
    description: 'Licensed electrician.',
  },
  {
    id: 'l04',
    title: 'Weekend plumber',
    category: 'plumbing',
    city: 'Salem',
    ownerId: 'p99',
    description: 'Weekend availability.',
  },
]

const PROFILES = [
  { id: 'p01', name: 'Rosa Delgado', rating: 4.9, responseTimeHours: 2 },
  { id: 'p02', name: 'Marco Ruiz', rating: 4.4, responseTimeHours: 1 },
  { id: 'p03', name: 'Sam Whitfield', rating: 4.7, responseTimeHours: 5 },
]

test('results carry the correct owner profile for each listing', async () => {
  const store = new FakeStore(LISTINGS, PROFILES)
  const results = await searchDirectory(store, 'plumber')
  const byId = new Map(results.map((result) => [result.id, result]))
  assert.equal(byId.get('l01').owner.name, 'Rosa Delgado')
  assert.equal(byId.get('l02').owner.name, 'Marco Ruiz')
})

test('best-matching listing ranks first', async () => {
  const store = new FakeStore(LISTINGS, PROFILES)
  const results = await searchDirectory(store, 'plumber')
  // l02 matches in title, category, and description; the rest match less.
  assert.equal(results[0].id, 'l02')
  assert.ok(!results.some((result) => result.id === 'l03'), 'non-matching listing must be excluded')
})

test('limit option caps the number of results', async () => {
  const store = new FakeStore(LISTINGS, PROFILES)
  const results = await searchDirectory(store, 'plumber', { limit: 2 })
  assert.equal(results.length, 2)
})

test('query with no matches returns an empty list', async () => {
  const store = new FakeStore(LISTINGS, PROFILES)
  assert.deepEqual(await searchDirectory(store, 'zzzzz'), [])
})

test('listing whose owner profile is missing still appears, without an owner', async () => {
  const store = new FakeStore(LISTINGS, PROFILES)
  const results = await searchDirectory(store, 'plumber')
  const orphan = results.find((result) => result.id === 'l04')
  assert.ok(orphan, 'listing with missing owner profile must still be returned')
  assert.ok(orphan.owner == null, 'missing profile must resolve to an empty owner')
})
