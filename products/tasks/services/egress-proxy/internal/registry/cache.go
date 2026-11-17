package registry

import (
	"container/list"
	"context"
	"crypto/rand"
	"errors"
	"math/big"
	"sync"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
)

const (
	leaseDuration = 30 * time.Second
	clockMargin   = 3 * time.Second
)

type CacheConfig struct {
	Lookup               identity.Lookup
	MaxEntries           int
	MaxConcurrentLookups int
}

type clockReading struct {
	wall    time.Time
	elapsed time.Duration
}

type cacheEntry struct {
	key          identity.LookupRequest
	registration identity.Registration
	deadline     time.Duration
	refreshAt    time.Duration
	err          error
}

type pendingLookup struct {
	done  chan struct{}
	entry cacheEntry
}

type Cache struct {
	lookup     identity.Lookup
	maxEntries int
	maxPending int
	started    time.Time
	clock      func() clockReading
	mu         sync.Mutex
	entries    map[identity.LookupRequest]*list.Element
	lru        list.List
	pending    map[identity.LookupRequest]*pendingLookup
}

func NewCache(config CacheConfig) (*Cache, error) {
	if config.Lookup == nil || config.MaxEntries <= 0 || config.MaxConcurrentLookups <= 0 {
		return nil, errors.New("invalid registry cache configuration")
	}
	started := time.Now()
	return &Cache{
		lookup: config.Lookup, maxEntries: config.MaxEntries, maxPending: config.MaxConcurrentLookups,
		started: started,
		clock: func() clockReading {
			now := time.Now()
			return clockReading{wall: now, elapsed: now.Sub(started)}
		},
		entries: make(map[identity.LookupRequest]*list.Element),
		pending: make(map[identity.LookupRequest]*pendingLookup),
	}, nil
}

func (c *Cache) validClock(now clockReading) bool {
	drift := now.wall.Round(0).Sub(c.started.Round(0)) - now.elapsed
	return now.elapsed >= 0 && drift >= -clockMargin && drift <= clockMargin
}

func (e cacheEntry) valid(now clockReading) bool {
	return now.elapsed < e.deadline && now.wall.Before(e.registration.LeaseExpiresAt.Add(-clockMargin))
}

func refreshDelay() time.Duration {
	jitter, err := rand.Int(rand.Reader, big.NewInt(int64(2*time.Second)))
	if err != nil {
		return 20 * time.Second
	}
	return 19*time.Second + time.Duration(jitter.Int64())
}

func (c *Cache) Lookup(ctx context.Context, key identity.LookupRequest) (identity.Registration, error) {
	now := c.clock()
	if ctx.Err() != nil || !c.validClock(now) {
		return identity.Registration{}, identity.ErrUnavailable
	}
	c.mu.Lock()
	var previous cacheEntry
	if element := c.entries[key]; element != nil {
		previous = element.Value.(cacheEntry)
		leased := previous.valid(now)
		retryLater := now.elapsed < previous.refreshAt
		if retryLater && (leased || previous.err != nil) || leased && (c.pending[key] != nil || len(c.pending) >= c.maxPending) {
			c.lru.MoveToFront(element)
			c.mu.Unlock()
			return c.result(ctx, previous)
		}
	}
	if pending := c.pending[key]; pending != nil {
		c.mu.Unlock()
		select {
		case <-ctx.Done():
			return identity.Registration{}, identity.ErrUnavailable
		case <-pending.done:
			return c.result(ctx, pending.entry)
		}
	}
	if len(c.pending) >= c.maxPending {
		c.mu.Unlock()
		return identity.Registration{}, identity.ErrUnavailable
	}
	pending := &pendingLookup{done: make(chan struct{})}
	c.pending[key] = pending
	c.mu.Unlock()

	entry := c.refresh(ctx, key, previous, now)
	c.mu.Lock()
	c.remove(key)
	c.entries[key] = c.lru.PushFront(entry)
	if c.lru.Len() > c.maxEntries {
		c.remove(c.lru.Back().Value.(cacheEntry).key)
	}
	pending.entry = entry
	delete(c.pending, key)
	close(pending.done)
	c.mu.Unlock()
	return c.result(ctx, entry)
}

func (c *Cache) refresh(ctx context.Context, key identity.LookupRequest, previous cacheEntry, started clockReading) cacheEntry {
	registration, err := c.lookup(ctx, key)
	finished := c.clock()
	entry := cacheEntry{key: key, registration: registration}
	if err == nil {
		remaining := registration.LeaseExpiresAt.Sub(started.wall) - clockMargin
		entry.deadline = started.elapsed + min(remaining, leaseDuration-clockMargin)
		entry.refreshAt = started.elapsed + refreshDelay()
		if registration.Revoked || remaining <= 0 || !entry.valid(finished) {
			err = identity.ErrUnauthorized
		} else if registration.TeamID != key.TeamID || registration.RunID != key.RunID || registration.ExecutionID != key.ExecutionID ||
			registration.LeaseExpiresAt.Sub(finished.wall) > leaseDuration+clockMargin || !c.validClock(finished) {
			err = identity.ErrUnavailable
		}
	}
	if ctx.Err() != nil && !errors.Is(err, identity.ErrUnauthorized) {
		err = identity.ErrUnavailable
	}
	if err != nil {
		entry = cacheEntry{key: key}
		if errors.Is(err, identity.ErrUnauthorized) {
			entry.err = identity.ErrUnauthorized
		} else {
			if previous.valid(finished) {
				entry = previous
			}
			entry.err = identity.ErrUnavailable
		}
		entry.refreshAt = finished.elapsed + time.Second
	}
	return entry
}

func (c *Cache) result(ctx context.Context, entry cacheEntry) (identity.Registration, error) {
	now := c.clock()
	if ctx.Err() != nil || !c.validClock(now) {
		return identity.Registration{}, identity.ErrUnavailable
	}
	if entry.valid(now) {
		return entry.registration, nil
	}
	if entry.err != nil {
		return identity.Registration{}, entry.err
	}
	return identity.Registration{}, identity.ErrUnavailable
}

func (c *Cache) remove(key identity.LookupRequest) {
	if element := c.entries[key]; element != nil {
		c.lru.Remove(element)
		delete(c.entries, key)
	}
}
