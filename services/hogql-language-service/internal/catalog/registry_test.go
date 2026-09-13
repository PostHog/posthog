package catalog

import (
	"testing"
	"time"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/serviceauth"
)

func TestRegistryIsolatesCatalogsAndReplacesRevisionAtomically(t *testing.T) {
	now := time.Unix(100, 0)
	registry := newRegistry(2, 1<<20, time.Hour, func() time.Time { return now })
	first := &Catalog{Tables: map[string]Table{"events": {Name: "events"}}, Properties: map[string][]Property{}}
	second := &Catalog{Tables: map[string]Table{"persons": {Name: "persons"}}, Properties: map[string][]Property{}}
	if err := registry.Put(serviceauth.Authorization{TeamID: 1, UserID: 10}, "1", first); err != nil {
		t.Fatal(err)
	}
	if err := registry.Put(serviceauth.Authorization{TeamID: 2, UserID: 20}, "7", second); err != nil {
		t.Fatal(err)
	}
	loaded, revision, ok := registry.Get(serviceauth.Authorization{TeamID: 1, UserID: 10})
	if !ok || revision != "1" || loaded.Tables["events"].Name != "events" {
		t.Fatalf("unexpected first catalog: %#v, %q, %t", loaded, revision, ok)
	}
	if _, exists := loaded.Tables["persons"]; exists {
		t.Fatal("one team and user scope received another scope's table")
	}
	if err := registry.Put(serviceauth.Authorization{TeamID: 1, UserID: 10}, "2", second); err != nil {
		t.Fatal(err)
	}
	loaded, revision, ok = registry.Get(serviceauth.Authorization{TeamID: 1, UserID: 10})
	if !ok || revision != "2" || loaded.Tables["persons"].Name != "persons" {
		t.Fatalf("replacement was not visible: %#v, %q, %t", loaded, revision, ok)
	}
}

func TestRegistryExpiresAndEvictsLeastRecentlyUsedCatalogs(t *testing.T) {
	now := time.Unix(100, 0)
	registry := newRegistry(2, 1<<20, time.Minute, func() time.Time { return now })
	value := &Catalog{Tables: map[string]Table{}, Properties: map[string][]Property{}}
	for _, scope := range []serviceauth.Authorization{{TeamID: 1, UserID: 10}, {TeamID: 2, UserID: 20}} {
		if err := registry.Put(scope, "1", value); err != nil {
			t.Fatal(err)
		}
		now = now.Add(time.Second)
	}
	if _, _, ok := registry.Get(serviceauth.Authorization{TeamID: 1, UserID: 10}); !ok {
		t.Fatal("first team and user scope unexpectedly missing")
	}
	now = now.Add(time.Second)
	if err := registry.Put(serviceauth.Authorization{TeamID: 3, UserID: 30}, "1", value); err != nil {
		t.Fatal(err)
	}
	if _, _, ok := registry.Get(serviceauth.Authorization{TeamID: 2, UserID: 20}); ok {
		t.Fatal("least recently used catalog was not evicted")
	}
	now = now.Add(time.Minute)
	if stats := registry.Stats(); stats.Catalogs != 0 {
		t.Fatalf("expired catalogs remain: %#v", stats)
	}
}

func TestRegistryExpiresActiveCatalogFromPublicationTime(t *testing.T) {
	now := time.Unix(100, 0)
	registry := newRegistry(1, 1<<20, time.Minute, func() time.Time { return now })
	scope := serviceauth.Authorization{TeamID: 1, UserID: 10}
	value := &Catalog{Tables: map[string]Table{}, Properties: map[string][]Property{}}
	if err := registry.Put(scope, "1", value); err != nil {
		t.Fatal(err)
	}
	now = now.Add(45 * time.Second)
	if _, _, ok := registry.Get(scope); !ok {
		t.Fatal("catalog expired before its publication TTL")
	}
	now = now.Add(16 * time.Second)
	if _, _, ok := registry.Get(scope); ok {
		t.Fatal("catalog access extended its publication TTL")
	}
}

func TestRegistryEvictsCatalogsToStayWithinMemoryBudget(t *testing.T) {
	now := time.Unix(100, 0)
	value := &Catalog{Tables: map[string]Table{"events": {Name: "events", Fields: map[string]Field{"long_field_name": {Name: "long_field_name", Type: "String"}}}}, Properties: map[string][]Property{}}
	size := estimatedSize(value)
	registry := newRegistry(10, size, time.Hour, func() time.Time { return now })
	first := serviceauth.Authorization{TeamID: 1, UserID: 10}
	second := serviceauth.Authorization{TeamID: 2, UserID: 20}
	if err := registry.Put(first, "1", value); err != nil {
		t.Fatal(err)
	}
	if err := registry.Put(second, "1", value); err != nil {
		t.Fatal(err)
	}
	if _, _, ok := registry.Get(first); ok {
		t.Fatal("oldest catalog was not evicted to meet the memory budget")
	}
	if _, _, ok := registry.Get(second); !ok {
		t.Fatal("new catalog was not retained")
	}
}
