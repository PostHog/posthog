package catalog

import (
	"slices"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"
)

type Field struct {
	Name              string `json:"name"`
	Type              string `json:"type"`
	Relation          string `json:"relation,omitempty"`
	PropertyNamespace string `json:"propertyNamespace,omitempty"`
}

type RelationDefinition struct {
	Fields             map[string]Field  `json:"fields"`
	Table              string            `json:"table,omitempty"`
	PropertyNamespaces map[string]string `json:"propertyNamespaces,omitempty"`
}

type Table struct {
	ID     string           `json:"id"`
	Name   string           `json:"name"`
	Type   string           `json:"type"`
	Fields map[string]Field `json:"fields"`
}

type Property struct {
	Name      string `json:"name"`
	ValueType string `json:"property_type"`
}

type Catalog struct {
	Tables       map[string]Table              `json:"tables"`
	TableAliases map[string]string             `json:"tableAliases,omitempty"`
	Properties   map[string][]Property         `json:"properties"`
	Relations    map[string]RelationDefinition `json:"relations,omitempty"`
}

type Entry struct {
	Name string
	Type string
}

type Index struct {
	entries []Entry
}

type PreparedTable struct {
	Name   string
	Type   string
	Fields PreparedFields
}

type PreparedRelation struct {
	Fields             *PreparedFields
	propertyNamespaces map[string]string
	ownedFields        bool
}

type FieldTraversal struct {
	Relation          *PreparedRelation
	PropertyNamespace string
}

type PreparedFields struct {
	Index
	traversals map[string]FieldTraversal
}

type PreparedCatalog struct {
	tables         Index
	tableSpellings Index
	tablesByName   map[string]int
	tableValues    []PreparedTable
	properties     map[string]*Index
	relations      map[string]*PreparedRelation
	valid          bool
	tableCount     int
	propertyCount  int
	hasAliases     bool
	estimatedBytes int64
}

func Prepare(value *Catalog) *PreparedCatalog {
	if value == nil {
		return nil
	}
	prepared := &PreparedCatalog{
		tablesByName: make(map[string]int, len(value.Tables)),
		tableValues:  make([]PreparedTable, 0, len(value.Tables)),
		properties:   make(map[string]*Index, len(value.Properties)),
		valid:        ValidateCatalog(value) == nil,
		tableCount:   len(value.Tables),
	}
	fieldCount := 0
	for _, table := range value.Tables {
		fieldCount += len(table.Fields)
	}
	fieldEntries := make([]Entry, 0, fieldCount)
	tableEntries := make([]Entry, 0, len(value.Tables))
	types := map[string]string{}
	for name, table := range value.Tables {
		fieldStart := len(fieldEntries)
		for fieldName, field := range table.Fields {
			fieldEntries = append(fieldEntries, newEntry(fieldName, intern(types, field.Type)))
		}
		tableType := intern(types, table.Type)
		preparedTable := PreparedTable{Name: name, Type: tableType, Fields: PreparedFields{Index: newIndex(fieldEntries[fieldStart:])}}
		prepared.tablesByName[name] = len(prepared.tableValues)
		prepared.tableValues = append(prepared.tableValues, preparedTable)
		tableEntries = append(tableEntries, newEntry(name, tableType))
	}
	prepared.tables = newIndex(tableEntries)
	if len(value.Relations) > 0 {
		prepared.relations = make(map[string]*PreparedRelation, len(value.Relations))
	}
	for name, relation := range value.Relations {
		preparedRelation := &PreparedRelation{}
		if relation.Fields != nil {
			entries := make([]Entry, 0, len(relation.Fields))
			for fieldName, field := range relation.Fields {
				entries = append(entries, newEntry(fieldName, intern(types, field.Type)))
			}
			fields := PreparedFields{Index: newIndex(entries)}
			preparedRelation.Fields = &fields
			preparedRelation.ownedFields = true
		} else if tableIndex, ok := prepared.tablesByName[relation.Table]; ok {
			preparedRelation.Fields = &prepared.tableValues[tableIndex].Fields
		}
		if len(relation.PropertyNamespaces) > 0 {
			preparedRelation.propertyNamespaces = make(map[string]string, len(relation.PropertyNamespaces))
			for fieldName, namespace := range relation.PropertyNamespaces {
				preparedRelation.propertyNamespaces[fieldName] = namespace
			}
		}
		prepared.relations[name] = preparedRelation
	}
	prepareTraversals := func(fields map[string]Field, target *PreparedFields) {
		for fieldName, field := range fields {
			if field.Relation == "" && field.PropertyNamespace == "" {
				continue
			}
			if target.traversals == nil {
				target.traversals = make(map[string]FieldTraversal)
			}
			target.traversals[fieldName] = FieldTraversal{
				Relation: prepared.relations[field.Relation], PropertyNamespace: field.PropertyNamespace,
			}
		}
	}
	for name, table := range value.Tables {
		prepareTraversals(table.Fields, &prepared.tableValues[prepared.tablesByName[name]].Fields)
	}
	for name, relation := range value.Relations {
		if relation.Fields != nil {
			prepareTraversals(relation.Fields, prepared.relations[name].Fields)
		}
	}
	prepared.tableSpellings = prepared.tables
	if prepared.valid {
		spellingEntries := slices.Clone(tableEntries)
		for alias, target := range value.TableAliases {
			if alias == target {
				continue
			}
			prepared.hasAliases = true
			prepared.tablesByName[alias] = prepared.tablesByName[target]
			spellingEntries = append(spellingEntries, newEntry(alias, target))
		}
		if prepared.hasAliases {
			prepared.tableSpellings = newIndex(spellingEntries)
		}
	}
	for namespace, properties := range value.Properties {
		entries := make([]Entry, len(properties))
		for index, property := range properties {
			entries[index] = newEntry(property.Name, intern(types, property.ValueType))
		}
		index := newIndex(entries)
		prepared.properties[namespace] = &index
		prepared.propertyCount += len(entries)
	}
	prepared.estimatedBytes = prepared.estimateSize()
	return prepared
}

func (f *PreparedFields) Traversal(name string) (FieldTraversal, bool) {
	entry, ok := f.Exact(name)
	if !ok || f.traversals == nil {
		return FieldTraversal{}, false
	}
	traversal, ok := f.traversals[entry.Name]
	return traversal, ok
}

func (r *PreparedRelation) Traversal(name string) (FieldTraversal, bool) {
	if r == nil || r.Fields == nil {
		return FieldTraversal{}, false
	}
	entry, ok := r.Fields.Exact(name)
	if !ok {
		return FieldTraversal{}, false
	}
	if namespace, ok := r.propertyNamespaces[entry.Name]; ok {
		return FieldTraversal{PropertyNamespace: namespace}, true
	}
	return r.Fields.Traversal(entry.Name)
}

func (c *PreparedCatalog) Table(name string) (*PreparedTable, bool) {
	index, ok := c.tablesByName[name]
	if !ok {
		return nil, false
	}
	return &c.tableValues[index], true
}

func (c *PreparedCatalog) Tables() *Index {
	return &c.tables
}

func (c *PreparedCatalog) TableSpellings() *Index {
	return &c.tableSpellings
}

func (c *PreparedCatalog) TableSuggestions(prefix string, excluded map[string]bool) []Entry {
	return c.tableSuggestions(prefix, excluded, nil)
}

func (c *PreparedCatalog) TableSuggestionsMatching(prefix string, excluded map[string]bool, matches func(Entry) bool) []Entry {
	return c.tableSuggestions(prefix, excluded, matches)
}

func (c *PreparedCatalog) tableSuggestions(prefix string, excluded map[string]bool, matches func(Entry) bool) []Entry {
	accepted := func(entry Entry) bool {
		return !excluded[entry.Name] && (matches == nil || matches(entry))
	}
	if !c.hasAliases {
		candidates := c.tables.Prefix(prefix)
		if len(excluded) == 0 && matches == nil {
			return candidates
		}
		result := make([]Entry, 0, len(candidates))
		for _, candidate := range candidates {
			if accepted(candidate) {
				result = append(result, candidate)
			}
		}
		return result
	}
	candidates := c.tableSpellings.Prefix(prefix)
	canonicalMatches := make(map[int]bool, len(candidates))
	for _, candidate := range candidates {
		if !accepted(candidate) {
			continue
		}
		index := c.tablesByName[candidate.Name]
		if c.tableValues[index].Name == candidate.Name {
			canonicalMatches[index] = true
		}
	}
	seen := make(map[int]bool, len(candidates))
	result := make([]Entry, 0, len(candidates))
	for _, candidate := range candidates {
		if !accepted(candidate) {
			continue
		}
		index := c.tablesByName[candidate.Name]
		canonical := c.tableValues[index].Name == candidate.Name
		if seen[index] || (!canonical && canonicalMatches[index]) {
			continue
		}
		seen[index] = true
		result = append(result, candidate)
	}
	return result
}

func (c *PreparedCatalog) CanonicalTableName(name string) (string, bool) {
	table, ok := c.Table(name)
	if !ok {
		return "", false
	}
	return table.Name, true
}

func (c *PreparedCatalog) Properties(namespace string) *Index {
	return c.properties[namespace]
}

func (c *PreparedCatalog) TableCount() int {
	return c.tableCount
}

func (c *PreparedCatalog) PropertyCount() int {
	return c.propertyCount
}

func (c *PreparedCatalog) EstimatedBytes() int64 {
	return c.estimatedBytes
}

func (i *Index) Exact(name string) (Entry, bool) {
	if i == nil {
		return Entry{}, false
	}
	position := sort.Search(len(i.entries), func(index int) bool {
		return compareFold(i.entries[index].Name, name) >= 0
	})
	if position == len(i.entries) || compareFold(i.entries[position].Name, name) != 0 {
		return Entry{}, false
	}
	return i.entries[position], true
}

func (i *Index) Prefix(prefix string) []Entry {
	if i == nil {
		return nil
	}
	foldedPrefix := foldName(prefix)
	start := sort.Search(len(i.entries), func(index int) bool {
		return compareFold(i.entries[index].Name, foldedPrefix) >= 0
	})
	end := len(i.entries)
	if upperBound, ok := prefixUpperBound(foldedPrefix); ok {
		end = sort.Search(len(i.entries), func(index int) bool {
			return compareFold(i.entries[index].Name, upperBound) >= 0
		})
	}
	return i.entries[start:end]
}

func (i *Index) Entries() []Entry {
	if i == nil {
		return nil
	}
	return i.entries
}

func newEntry(name, valueType string) Entry {
	return Entry{Name: name, Type: valueType}
}

func intern(values map[string]string, value string) string {
	if existing, ok := values[value]; ok {
		return existing
	}
	values[value] = value
	return value
}

func newIndex(entries []Entry) Index {
	if !slices.IsSortedFunc(entries, compareEntries) {
		slices.SortFunc(entries, compareEntries)
	}
	return Index{entries: entries}
}

func compareEntries(left, right Entry) int {
	comparison := compareFold(left.Name, right.Name)
	if comparison == 0 {
		return strings.Compare(left.Name, right.Name)
	}
	return comparison
}

func (c *PreparedCatalog) estimateSize() int64 {
	var size int64
	for _, entry := range c.tables.entries {
		size += entrySize(entry) + 64
		table := &c.tableValues[c.tablesByName[entry.Name]]
		for _, field := range table.Fields.entries {
			size += entrySize(field)
		}
	}
	if c.hasAliases {
		for _, entry := range c.tableSpellings.entries {
			if c.tableValues[c.tablesByName[entry.Name]].Name == entry.Name {
				size += 32
				continue
			}
			size += entrySize(entry) + 32
		}
	}
	for namespace, properties := range c.properties {
		size += int64(len(namespace) + 64)
		for _, property := range properties.entries {
			size += entrySize(property)
		}
	}
	for name, relation := range c.relations {
		size += int64(len(name) + 64)
		if relation.ownedFields && relation.Fields != nil {
			for _, field := range relation.Fields.entries {
				size += entrySize(field)
				if traversal, ok := relation.Fields.traversals[field.Name]; ok {
					size += int64(len(traversal.PropertyNamespace) + 48)
				}
			}
			if relation.Fields.traversals != nil {
				size += 64
			}
		}
		if relation.propertyNamespaces != nil {
			size += 64
			for fieldName, namespace := range relation.propertyNamespaces {
				size += int64(len(fieldName) + len(namespace) + 48)
			}
		}
	}
	for _, table := range c.tableValues {
		if table.Fields.traversals != nil {
			size += 64
		}
		for _, traversal := range table.Fields.traversals {
			size += int64(len(traversal.PropertyNamespace) + 48)
		}
	}
	return size
}

func entrySize(entry Entry) int64 {
	return int64(len(entry.Name) + len(entry.Type) + 32)
}

func compareFold(left, right string) int {
	for len(left) > 0 && len(right) > 0 {
		leftRune, leftSize := utf8.DecodeRuneInString(left)
		rightRune, rightSize := utf8.DecodeRuneInString(right)
		leftRune = foldRune(leftRune)
		rightRune = foldRune(rightRune)
		if leftRune < rightRune {
			return -1
		}
		if leftRune > rightRune {
			return 1
		}
		left = left[leftSize:]
		right = right[rightSize:]
	}
	if len(left) > 0 {
		return 1
	}
	if len(right) > 0 {
		return -1
	}
	return 0
}

func foldName(value string) string {
	return strings.Map(foldRune, value)
}

func foldRune(value rune) rune {
	if value >= 'A' && value <= 'Z' {
		return value + 'a' - 'A'
	}
	if value >= 'a' && value <= 'z' {
		return value
	}
	canonical := value
	for candidate := unicode.SimpleFold(value); candidate != value; candidate = unicode.SimpleFold(candidate) {
		if candidate >= 'a' && candidate <= 'z' {
			return candidate
		}
		if candidate < canonical {
			canonical = candidate
		}
	}
	return canonical
}

func prefixUpperBound(prefix string) (string, bool) {
	characters := []rune(prefix)
	for index := len(characters) - 1; index >= 0; index-- {
		if characters[index] == utf8.MaxRune {
			continue
		}
		characters[index]++
		if characters[index] >= 0xD800 && characters[index] <= 0xDFFF {
			characters[index] = 0xE000
		}
		return string(characters[:index+1]), true
	}
	return "", false
}
