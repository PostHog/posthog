import { LISTINGS, PROFILES } from './data.js'

// Each store call simulates one round trip to the backing database.
const CALL_LATENCY_MS = 40

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export class DirectoryStore {
  constructor({ listings = LISTINGS, profiles = PROFILES, latencyMs = CALL_LATENCY_MS } = {}) {
    this.listings = listings
    this.profiles = new Map(profiles.map((profile) => [profile.id, profile]))
    this.latencyMs = latencyMs
  }

  async searchListings(query) {
    await sleep(this.latencyMs)
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean)
    if (terms.length === 0) {
      return []
    }
    return this.listings.filter((listing) =>
      terms.some(
        (term) =>
          listing.title.toLowerCase().includes(term) ||
          listing.category.toLowerCase().includes(term) ||
          listing.description.toLowerCase().includes(term)
      )
    )
  }

  async getListing(id) {
    await sleep(this.latencyMs)
    return this.listings.find((listing) => listing.id === id) ?? null
  }

  async getProfile(id) {
    await sleep(this.latencyMs)
    return this.profiles.get(id) ?? null
  }

  async getProfilesByIds(ids) {
    await sleep(this.latencyMs)
    const unique = [...new Set(ids)]
    return unique.map((id) => this.profiles.get(id)).filter(Boolean)
  }
}
