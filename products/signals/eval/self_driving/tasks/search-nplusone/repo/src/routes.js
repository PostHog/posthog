import { capture } from './analytics.js'
import { searchDirectory } from './search.js'

export function registerRoutes(app, store) {
  app.get('/api/search', async (req, res) => {
    const query = String(req.query.q ?? '')
    const startedAt = Date.now()
    const results = await searchDirectory(store, query)
    capture(req.get('x-user-id') ?? 'anonymous', 'directory_search', {
      query,
      result_count: results.length,
      duration_ms: Date.now() - startedAt,
    })
    res.json({ results })
  })

  app.get('/api/listings/:id', async (req, res) => {
    const listing = await store.getListing(req.params.id)
    if (!listing) {
      return res.status(404).json({ error: 'Listing not found' })
    }
    const owner = await store.getProfile(listing.ownerId)
    capture(req.get('x-user-id') ?? 'anonymous', 'listing_opened', { listing_id: listing.id })
    res.json({ listing: { ...listing, owner } })
  })

  app.post('/api/listings/:id/contact', async (req, res) => {
    const listing = await store.getListing(req.params.id)
    if (!listing) {
      return res.status(404).json({ error: 'Listing not found' })
    }
    capture(req.get('x-user-id') ?? 'anonymous', 'contact_requested', { listing_id: listing.id })
    res.status(202).json({ status: 'requested', listingId: listing.id })
  })
}
