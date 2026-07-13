function scoreListing(listing, terms) {
  let score = 0
  const title = listing.title.toLowerCase()
  const category = listing.category.toLowerCase()
  const description = listing.description.toLowerCase()
  for (const term of terms) {
    if (title.includes(term)) {
      score += 3
    }
    if (category.includes(term)) {
      score += 2
    }
    if (description.includes(term)) {
      score += 1
    }
  }
  return score
}

export function rankListings(listings, query) {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (terms.length === 0) {
    return []
  }
  return listings
    .map((listing) => ({ listing, score: scoreListing(listing, terms) }))
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score || a.listing.id.localeCompare(b.listing.id))
    .map((entry) => entry.listing)
}
