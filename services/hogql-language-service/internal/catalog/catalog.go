package catalog

type Field struct {
	Name string `json:"name"`
	Type string `json:"type"`
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
	Tables     map[string]Table      `json:"tables"`
	Properties map[string][]Property `json:"properties"`
}
