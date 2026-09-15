package catalog

import (
	"errors"
	"sync"
	"time"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/serviceauth"
)

var (
	ErrInvalidScope    = errors.New("team ID and user ID must be positive")
	ErrInvalidRevision = errors.New("invalid catalog revision")
	ErrCatalogTooLarge = errors.New("catalog exceeds cache capacity")
)

type Registry struct {
	mu         sync.Mutex
	entries    map[serviceauth.Authorization]registryEntry
	maxEntries int
	maxBytes   int64
	totalBytes int64
	ttl        time.Duration
	now        func() time.Time
}

type registryEntry struct {
	catalog    *Catalog
	revision   string
	createdAt  time.Time
	lastAccess time.Time
	sizeBytes  int64
}

type RegistryStats struct {
	Catalogs   int `json:"catalogs"`
	Tables     int `json:"tables"`
	Properties int `json:"properties"`
}

func NewRegistry(maxEntries int, maxBytes int64, ttl time.Duration) *Registry {
	return newRegistry(maxEntries, maxBytes, ttl, time.Now)
}

func newRegistry(maxEntries int, maxBytes int64, ttl time.Duration, now func() time.Time) *Registry {
	return &Registry{entries: map[serviceauth.Authorization]registryEntry{}, maxEntries: maxEntries, maxBytes: maxBytes, ttl: ttl, now: now}
}

func (r *Registry) Put(authorization serviceauth.Authorization, revision string, value *Catalog) error {
	if !authorization.Valid() {
		return ErrInvalidScope
	}
	if revision == "" || len(revision) > 128 {
		return ErrInvalidRevision
	}
	if value == nil || value.Tables == nil || value.Properties == nil {
		return errors.New("catalog must contain tables and properties")
	}
	sizeBytes := estimatedSize(value)
	if sizeBytes > r.maxBytes {
		return ErrCatalogTooLarge
	}

	r.mu.Lock()
	defer r.mu.Unlock()
	now := r.now()
	r.removeExpired(now)
	if existing, exists := r.entries[authorization]; exists {
		r.totalBytes -= existing.sizeBytes
		delete(r.entries, authorization)
	}
	for len(r.entries) >= r.maxEntries || r.totalBytes+sizeBytes > r.maxBytes {
		r.removeLeastRecentlyUsed()
	}
	r.entries[authorization] = registryEntry{catalog: value, revision: revision, createdAt: now, lastAccess: now, sizeBytes: sizeBytes}
	r.totalBytes += sizeBytes
	return nil
}

func (r *Registry) Get(authorization serviceauth.Authorization) (*Catalog, string, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	now := r.now()
	r.removeExpired(now)
	entry, ok := r.entries[authorization]
	if !ok {
		return nil, "", false
	}
	entry.lastAccess = now
	r.entries[authorization] = entry
	return entry.catalog, entry.revision, true
}

func (r *Registry) Delete(authorization serviceauth.Authorization) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.entries[authorization]; !exists {
		return false
	}
	r.totalBytes -= r.entries[authorization].sizeBytes
	delete(r.entries, authorization)
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
	for authorization, entry := range r.entries {
		if now.Sub(entry.createdAt) >= r.ttl {
			r.totalBytes -= entry.sizeBytes
			delete(r.entries, authorization)
		}
	}
}

func (r *Registry) removeLeastRecentlyUsed() {
	var oldestAuthorization serviceauth.Authorization
	found := false
	var oldest time.Time
	for authorization, entry := range r.entries {
		if !found || entry.lastAccess.Before(oldest) {
			oldestAuthorization = authorization
			oldest = entry.lastAccess
			found = true
		}
	}
	r.totalBytes -= r.entries[oldestAuthorization].sizeBytes
	delete(r.entries, oldestAuthorization)
}

func estimatedSize(value *Catalog) int64 {
	var size int64
	for name, table := range value.Tables {
		size += int64(len(name) + len(table.Name) + len(table.Type) + 64)
		for fieldName, field := range table.Fields {
			size += int64(len(fieldName) + len(field.Name) + len(field.Type) + 64)
		}
	}
	for namespace, properties := range value.Properties {
		size += int64(len(namespace) + 64)
		for _, property := range properties {
			size += int64(len(property.Name) + len(property.ValueType) + 32)
		}
	}
	return size
}
