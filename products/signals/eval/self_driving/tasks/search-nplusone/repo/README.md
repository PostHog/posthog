# Acme Directory

Search-first directory of local service providers. Users search for a trade
("plumber", "electrician"), browse ranked results, open listings, and request
contact with the provider.

As of 1.4 every search result shows the owner's profile card inline
(name, headline, rating, typical response time) so users can pick a provider
without opening each listing.

## Running

```bash
npm install
npm start
# server on http://localhost:4600
```

## API

- `GET /api/search?q=<query>` - ranked listings with owner profile attached
- `GET /api/listings/:id` - single listing
- `POST /api/listings/:id/contact` - request contact with the listing owner

## Architecture

- `src/store.js` - data access layer (in-memory today, will move to a real DB)
- `src/search.js` - search orchestration
- `src/rank.js` - relevance scoring
- `src/routes.js` - HTTP endpoints + product analytics
