package catalog

import (
	"errors"
	"sync"
	"time"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/serviceauth"
)

var (
	ErrInvalidScope     = errors.New("team ID and user ID must be positive")
	ErrInvalidRevision  = errors.New("invalid catalog revision")
	ErrInvalidCatalog   = errors.New("catalog must contain tables and properties")
	ErrInvalidAliases   = errors.New("table aliases must map non-empty alternate names directly to canonical table keys")
	ErrCatalogTooLarge  = errors.New("catalog exceeds cache capacity")
	ErrInvalidRelations = errors.New("catalog contains invalid traversal relations")
)

const MaxRelationDefinitions = 4096
const MaxRelationFields = 120000

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
	catalog    *PreparedCatalog
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

func ValidateRevision(revision string) error {
	if revision == "" || len(revision) > 128 {
		return ErrInvalidRevision
	}
	return nil
}

func ValidateCatalog(value *Catalog) error {
	if value == nil || value.Tables == nil || value.Properties == nil {
		return ErrInvalidCatalog
	}
	for alias, target := range value.TableAliases {
		if alias == "" || target == "" {
			return ErrInvalidAliases
		}
		if _, targetExists := value.Tables[target]; !targetExists {
			return ErrInvalidAliases
		}
		if _, aliasIsCanonical := value.Tables[alias]; aliasIsCanonical && alias != target {
			return ErrInvalidAliases
		}
	}
	if len(value.Relations) > MaxRelationDefinitions {
		return ErrInvalidRelations
	}
	relationFields := 0
	validateFields := func(fields map[string]Field) error {
		for _, field := range fields {
			if field.Relation != "" && field.PropertyNamespace != "" {
				return ErrInvalidRelations
			}
			if field.Relation != "" {
				if _, ok := value.Relations[field.Relation]; !ok {
					return ErrInvalidRelations
				}
			}
			if field.PropertyNamespace != "" {
				if _, ok := value.Properties[field.PropertyNamespace]; !ok {
					return ErrInvalidRelations
				}
			}
		}
		return nil
	}
	for _, table := range value.Tables {
		if err := validateFields(table.Fields); err != nil {
			return err
		}
	}
	for name, relation := range value.Relations {
		ownsFields := relation.Fields != nil
		referencesTable := relation.Table != ""
		if name == "" || ownsFields == referencesTable || (!referencesTable && len(relation.PropertyNamespaces) > 0) {
			return ErrInvalidRelations
		}
		relationFields += len(relation.Fields) + len(relation.PropertyNamespaces)
		if relationFields > MaxRelationFields {
			return ErrInvalidRelations
		}
		if ownsFields {
			if err := validateFields(relation.Fields); err != nil {
				return err
			}
			continue
		}
		table, ok := value.Tables[relation.Table]
		if !ok {
			return ErrInvalidRelations
		}
		for fieldName, namespace := range relation.PropertyNamespaces {
			field, fieldExists := table.Fields[fieldName]
			_, namespaceExists := value.Properties[namespace]
			if fieldName == "" || !fieldExists || field.Relation != "" || namespace == "" || !namespaceExists {
				return ErrInvalidRelations
			}
		}
	}
	return nil
}

func (r *Registry) Put(authorization serviceauth.Authorization, revision string, value *PreparedCatalog) error {
	if !authorization.Valid() {
		return ErrInvalidScope
	}
	if err := ValidateRevision(revision); err != nil {
		return err
	}
	if value == nil || !value.valid {
		return ErrInvalidCatalog
	}
	sizeBytes := value.EstimatedBytes()
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

func (r *Registry) Get(authorization serviceauth.Authorization) (*PreparedCatalog, string, bool) {
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
		stats.Tables += entry.catalog.TableCount()
		stats.Properties += entry.catalog.PropertyCount()
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
