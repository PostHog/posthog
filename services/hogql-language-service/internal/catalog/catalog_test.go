package catalog

import (
	"encoding/json"
	"errors"
	"fmt"
	"testing"
)

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

func TestPrepareCopiesAndValidatesTraversalRelations(t *testing.T) {
	value := &Catalog{
		Tables: map[string]Table{"events": {Fields: map[string]Field{"person": {Type: "lazy", Relation: "person"}}}},
		Relations: map[string]RelationDefinition{"person": {Fields: map[string]Field{
			"email": {Type: "String"}, "properties": {Type: "JSON", PropertyNamespace: "person"},
		}}},
		Properties: map[string][]Property{"person": {{Name: "plan", ValueType: "String"}}},
	}
	prepared := Prepare(value)
	value.Relations["person"] = RelationDefinition{Fields: map[string]Field{"changed": {Type: "String"}}}
	table, ok := prepared.Table("events")
	if !ok {
		t.Fatal("events table was not prepared")
	}
	traversal, ok := table.Fields.Traversal("person")
	if !ok || traversal.Relation == nil {
		t.Fatal("person traversal was not prepared")
	}
	if _, ok := traversal.Relation.Fields.Exact("email"); !ok {
		t.Fatal("prepared relation changed with source catalog")
	}
	if _, ok := traversal.Relation.Fields.Exact("changed"); ok {
		t.Fatal("prepared relation retained the source map")
	}

	for name, invalid := range map[string]*Catalog{
		"dangling relation":  {Tables: map[string]Table{"events": {Fields: map[string]Field{"person": {Relation: "missing"}}}}, Properties: map[string][]Property{}},
		"dangling namespace": {Tables: map[string]Table{"events": {Fields: map[string]Field{"properties": {PropertyNamespace: "missing"}}}}, Properties: map[string][]Property{}},
		"two targets":        {Tables: map[string]Table{"events": {Fields: map[string]Field{"person": {Relation: "person", PropertyNamespace: "person"}}}}, Relations: map[string]RelationDefinition{"person": {Fields: map[string]Field{}}}, Properties: map[string][]Property{"person": {}}},
		"relation union":     {Tables: map[string]Table{"events": {Fields: map[string]Field{}}}, Relations: map[string]RelationDefinition{"person": {Fields: map[string]Field{}, Table: "events"}}, Properties: map[string][]Property{}},
		"missing table":      {Tables: map[string]Table{"events": {Fields: map[string]Field{}}}, Relations: map[string]RelationDefinition{"person": {Table: "missing"}}, Properties: map[string][]Property{}},
		"table alias":        {Tables: map[string]Table{"events": {Fields: map[string]Field{}}}, TableAliases: map[string]string{"legacy_events": "events"}, Relations: map[string]RelationDefinition{"person": {Table: "legacy_events"}}, Properties: map[string][]Property{}},
		"bad override field": {Tables: map[string]Table{"events": {Fields: map[string]Field{}}}, Relations: map[string]RelationDefinition{"person": {Table: "events", PropertyNamespaces: map[string]string{"missing": "person"}}}, Properties: map[string][]Property{"person": {}}},
		"neither target":     {Tables: map[string]Table{"events": {Fields: map[string]Field{}}}, Relations: map[string]RelationDefinition{"person": {}}, Properties: map[string][]Property{}},
		"virtual override":   {Tables: map[string]Table{"events": {Fields: map[string]Field{}}}, Relations: map[string]RelationDefinition{"person": {Fields: map[string]Field{}, PropertyNamespaces: map[string]string{"properties": "person"}}}, Properties: map[string][]Property{"person": {}}},
		"unknown override":   {Tables: map[string]Table{"events": {Fields: map[string]Field{"properties": {Type: "JSON"}}}}, Relations: map[string]RelationDefinition{"person": {Table: "events", PropertyNamespaces: map[string]string{"properties": "missing"}}}, Properties: map[string][]Property{}},
		"relation override": {Tables: map[string]Table{"events": {Fields: map[string]Field{"owner": {Relation: "person"}}}}, Relations: map[string]RelationDefinition{
			"events": {Table: "events", PropertyNamespaces: map[string]string{"owner": "person"}}, "person": {Fields: map[string]Field{}},
		}, Properties: map[string][]Property{"person": {}}},
	} {
		t.Run(name, func(t *testing.T) {
			if ValidateCatalog(invalid) == nil {
				t.Fatal("invalid traversal catalog was accepted")
			}
		})
	}
}

func TestPrepareSharesTableRelationFieldsAndCopiesOverrides(t *testing.T) {
	value := &Catalog{
		Tables: map[string]Table{
			"events":  {Fields: map[string]Field{"person": {Type: "lazy", Relation: "person"}}},
			"persons": {Fields: map[string]Field{"email": {Type: "String"}, "properties": {Type: "JSON"}}},
		},
		Relations: map[string]RelationDefinition{
			"person": {Table: "persons", PropertyNamespaces: map[string]string{"properties": "person"}},
		},
		Properties: map[string][]Property{"person": {{Name: "plan", ValueType: "String"}}},
	}
	prepared := Prepare(value)
	persons, _ := prepared.Table("persons")
	events, _ := prepared.Table("events")
	personTraversal, ok := events.Fields.Traversal("person")
	if !ok || personTraversal.Relation.Fields != &persons.Fields {
		t.Fatal("table-backed relation did not share canonical prepared fields")
	}
	value.Relations["person"].PropertyNamespaces["properties"] = "changed"
	propertiesTraversal, ok := personTraversal.Relation.Traversal("PROPERTIES")
	if !ok || propertiesTraversal.PropertyNamespace != "person" {
		t.Fatalf("prepared override = %#v, %t", propertiesTraversal, ok)
	}
	if _, ok := persons.Fields.Traversal("properties"); ok {
		t.Fatal("relation override mutated canonical table metadata")
	}

	invalid := &Catalog{
		Tables:     map[string]Table{"events": {Fields: map[string]Field{}}},
		Relations:  map[string]RelationDefinition{"missing": {Table: "missing"}},
		Properties: map[string][]Property{},
	}
	if preparedInvalid := Prepare(invalid); preparedInvalid == nil || preparedInvalid.valid {
		t.Fatalf("invalid table-backed relation prepared as valid: %#v", preparedInvalid)
	}
}

func TestCatalogJSONPreservesEmptyVirtualRelation(t *testing.T) {
	value := Catalog{
		Tables:     map[string]Table{"events": {Fields: map[string]Field{}}},
		Relations:  map[string]RelationDefinition{"empty": {Fields: map[string]Field{}}},
		Properties: map[string][]Property{},
	}
	encoded, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	var decoded Catalog
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded.Relations["empty"].Fields == nil || ValidateCatalog(&decoded) != nil {
		t.Fatalf("empty virtual relation did not round trip: %s", encoded)
	}
}

func TestValidateCatalogRejectsTraversalLimits(t *testing.T) {
	relations := make(map[string]RelationDefinition, MaxRelationDefinitions+1)
	for index := 0; index <= MaxRelationDefinitions; index++ {
		relations[fmt.Sprintf("relation_%d", index)] = RelationDefinition{Fields: map[string]Field{}}
	}
	if err := ValidateCatalog(&Catalog{Tables: map[string]Table{"events": {Fields: map[string]Field{}}}, Properties: map[string][]Property{}, Relations: relations}); !errors.Is(err, ErrInvalidRelations) {
		t.Fatalf("relation definition limit error = %v", err)
	}

	fields := make(map[string]Field, MaxRelationFields/2+1)
	for index := 0; index <= MaxRelationFields/2; index++ {
		fields[fmt.Sprintf("field_%d", index)] = Field{Type: "String"}
	}
	overrides := make(map[string]string, len(fields))
	for fieldName := range fields {
		overrides[fieldName] = "shared"
	}
	if err := ValidateCatalog(&Catalog{
		Tables:     map[string]Table{"events": {Fields: fields}},
		Properties: map[string][]Property{"shared": {}},
		Relations: map[string]RelationDefinition{
			"left": {Fields: fields}, "right": {Table: "events", PropertyNamespaces: overrides},
		},
	}); !errors.Is(err, ErrInvalidRelations) {
		t.Fatalf("relation field limit error = %v", err)
	}
}
