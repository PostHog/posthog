package catalog

import "testing"

func TestIndexExactUsesUnicodeCaseFolding(t *testing.T) {
	index := newIndex([]Entry{newEntry("t", "String"), newEntry("ſ", "String")})

	entry, ok := index.Exact("s")
	if !ok || entry.Name != "ſ" {
		t.Fatalf("Exact(\"s\") = %#v, %t", entry, ok)
	}
}

func TestPreparedCatalogUsesExactTableNamesAndFoldedFieldPrefixes(t *testing.T) {
	prepared := Prepare(&Catalog{
		Tables: map[string]Table{
			"ς": {
				Fields: map[string]Field{
					"ςuffix": {Name: "ςuffix", Type: "String"},
				},
			},
		},
		Properties: map[string][]Property{},
	})

	if _, ok := prepared.Table("Σ"); ok {
		t.Fatal("Table(\"Σ\") matched ς")
	}
	table, ok := prepared.Table("ς")
	if !ok {
		t.Fatal("Table(\"ς\") did not find ς")
	}
	entry, ok := table.Fields.Exact("Σuffix")
	if !ok || entry.Name != "ςuffix" {
		t.Fatalf("Exact(\"Σuffix\") = %#v, %t", entry, ok)
	}
	prefix := table.Fields.Prefix("Σ")
	if len(prefix) != 1 || prefix[0].Name != "ςuffix" {
		t.Fatalf("Prefix(\"Σ\") = %#v", prefix)
	}
}

func TestPreparedCatalogRetainsCaseVariantTables(t *testing.T) {
	prepared := Prepare(&Catalog{
		Tables: map[string]Table{
			"Events": {Fields: map[string]Field{"upper": {Name: "upper", Type: "String"}}},
			"events": {Fields: map[string]Field{"lower": {Name: "lower", Type: "String"}}},
		},
		Properties: map[string][]Property{},
	})

	upper, upperOK := prepared.Table("Events")
	lower, lowerOK := prepared.Table("events")
	if !prepared.valid || !upperOK || !lowerOK || upper.Name != "Events" || lower.Name != "events" || prepared.TableCount() != 2 {
		t.Fatalf("prepared catalog = %#v", prepared)
	}
	prefix := prepared.Tables().Prefix("EV")
	if len(prefix) != 2 || prefix[0].Name != "Events" || prefix[1].Name != "events" {
		t.Fatalf("Prefix(\"EV\") = %#v", prefix)
	}
}

func TestPreparedCatalogResolvesAliasesToCanonicalTables(t *testing.T) {
	prepared := Prepare(&Catalog{
		Tables: map[string]Table{
			"postgres.demo.orders": {Type: "data_warehouse", Fields: map[string]Field{"id": {Type: "integer"}}},
		},
		TableAliases: map[string]string{"demo_postgres_orders": "postgres.demo.orders"},
		Properties:   map[string][]Property{},
	})

	canonical, canonicalOK := prepared.Table("postgres.demo.orders")
	alias, aliasOK := prepared.Table("demo_postgres_orders")
	if !canonicalOK || !aliasOK || canonical != alias {
		t.Fatalf("alias and canonical lookup did not share a prepared table: canonical=%p alias=%p", canonical, alias)
	}
	if _, ok := prepared.Table("Demo_postgres_orders"); ok {
		t.Fatal("alias lookup ignored exact case")
	}
	if field, ok := alias.Fields.Exact("id"); !ok || field.Type != "integer" {
		t.Fatalf("alias fields = %#v, %t", field, ok)
	}
}

func TestValidateCatalogRejectsInvalidAliases(t *testing.T) {
	base := func(aliases map[string]string) *Catalog {
		return &Catalog{
			Tables: map[string]Table{
				"orders": {Fields: map[string]Field{}},
				"events": {Fields: map[string]Field{}},
			},
			TableAliases: aliases,
			Properties:   map[string][]Property{},
		}
	}

	for name, aliases := range map[string]map[string]string{
		"empty alias":         {"": "orders"},
		"empty target":        {"legacy_orders": ""},
		"dangling target":     {"legacy_orders": "missing"},
		"chain":               {"legacy_orders": "older_orders", "older_orders": "orders"},
		"cycle":               {"legacy_orders": "older_orders", "older_orders": "legacy_orders"},
		"canonical collision": {"orders": "events"},
	} {
		t.Run(name, func(t *testing.T) {
			value := base(aliases)
			if err := ValidateCatalog(value); err == nil {
				t.Fatal("invalid alias map was accepted")
			}
			if prepared := Prepare(value); prepared == nil || prepared.valid {
				t.Fatalf("prepared invalid catalog = %#v", prepared)
			}
		})
	}

	if err := ValidateCatalog(base(map[string]string{"orders": "orders"})); err != nil {
		t.Fatalf("canonical identity alias was rejected: %v", err)
	}
}
