import { rankListings } from './rank.js'

const DEFAULT_LIMIT = 50

export async function searchDirectory(store, query, { limit = DEFAULT_LIMIT } = {}) {
  const candidates = await store.searchListings(query)
  const ranked = rankListings(candidates, query).slice(0, limit)
  const results = []
  for (const listing of ranked) {
    // Owner card is shown inline on every result since the profiles launch.
    const owner = await store.getProfile(listing.ownerId)
    results.push({ ...listing, owner })
  }
  return results
}
