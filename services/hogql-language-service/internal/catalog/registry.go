package catalog

import (
	"errors"
	"sync"
	"time"
)

var (
	ErrInvalidScope    = errors.New("team ID and user ID must be positive")
	ErrInvalidRevision = errors.New("invalid catalog revision")
)

type Scope struct {
	TeamID int64
	UserID int64
}

type Registry struct {
	mu         sync.Mutex
	entries    map[Scope]registryEntry
	maxEntries int
	ttl        time.Duration
	now        func() time.Time
}

type registryEntry struct {
	catalog    *Catalog
	revision   string
	lastAccess time.Time
}

type RegistryStats struct {
	Catalogs   int `json:"catalogs"`
	Tables     int `json:"tables"`
	Properties int `json:"properties"`
}

func NewRegistry(maxEntries int, ttl time.Duration) *Registry {
	return newRegistry(maxEntries, ttl, time.Now)
}

func newRegistry(maxEntries int, ttl time.Duration, now func() time.Time) *Registry {
	return &Registry{entries: map[Scope]registryEntry{}, maxEntries: maxEntries, ttl: ttl, now: now}
}

func (r *Registry) Put(scope Scope, revision string, value *Catalog) error {
	if scope.TeamID <= 0 || scope.UserID <= 0 {
		return ErrInvalidScope
	}
	if revision == "" || len(revision) > 128 {
		return ErrInvalidRevision
	}
	if value == nil || value.Tables == nil || value.Properties == nil {
		return errors.New("catalog must contain tables and properties")
	}

	r.mu.Lock()
	defer r.mu.Unlock()
	now := r.now()
	r.removeExpired(now)
	if _, exists := r.entries[scope]; !exists && len(r.entries) >= r.maxEntries {
		r.removeLeastRecentlyUsed()
	}
	r.entries[scope] = registryEntry{catalog: value, revision: revision, lastAccess: now}
	return nil
}

func (r *Registry) Get(scope Scope) (*Catalog, string, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	now := r.now()
	r.removeExpired(now)
	entry, ok := r.entries[scope]
	if !ok {
		return nil, "", false
	}
	entry.lastAccess = now
	r.entries[scope] = entry
	return entry.catalog, entry.revision, true
}

func (r *Registry) Delete(scope Scope) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.entries[scope]; !exists {
		return false
	}
	delete(r.entries, scope)
	return true
}

func (r *Registry) Stats() RegistryStats {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.removeExpired(r.now())
	stats := RegistryStats{Catalogs: len(r.entries)}
	for _, entry := range r.entries {
		stats.Tables += len(entry.catalog.Tables)
		for _, properties := range entry.catalog.Properties {
			stats.Properties += len(properties)
		}
	}
	return stats
}

func (r *Registry) removeExpired(now time.Time) {
	for scope, entry := range r.entries {
		if now.Sub(entry.lastAccess) >= r.ttl {
			delete(r.entries, scope)
		}
	}
}

func (r *Registry) removeLeastRecentlyUsed() {
	var oldestScope Scope
	found := false
	var oldest time.Time
	for scope, entry := range r.entries {
		if !found || entry.lastAccess.Before(oldest) {
			oldestScope = scope
			oldest = entry.lastAccess
			found = true
		}
	}
	delete(r.entries, oldestScope)
}
