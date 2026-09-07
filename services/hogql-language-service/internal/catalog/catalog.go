package catalog

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
)

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

var propertyNamespaces = []string{"event", "person", "session", "group:0", "group:1", "group:2", "group:3", "group:4"}

type Client struct {
	baseURL   *url.URL
	projectID string
	token     string
	http      *http.Client
}

func NewClient(baseURL, projectID, token string, httpClient *http.Client) (*Client, error) {
	parsed, err := url.Parse(baseURL)
	if err != nil {
		return nil, fmt.Errorf("parse PostHog URL: %w", err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return nil, fmt.Errorf("PostHog URL must use http or https")
	}
	if projectID == "" || token == "" {
		return nil, fmt.Errorf("project ID and API token are required")
	}
	return &Client{baseURL: parsed, projectID: projectID, token: token, http: httpClient}, nil
}

func (c *Client) Load(ctx context.Context) (*Catalog, error) {
	endpoint := c.baseURL.JoinPath("api", "projects", c.projectID, "query")
	body := strings.NewReader(`{"query":{"kind":"DatabaseSchemaQuery"}}`)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint.String(), body)
	if err != nil {
		return nil, fmt.Errorf("create schema request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("fetch schema: %w", err)
	}
	defer resp.Body.Close()
	limited := io.LimitReader(resp.Body, 256<<20)
	if resp.StatusCode != http.StatusOK {
		message, _ := io.ReadAll(io.LimitReader(limited, 4096))
		return nil, fmt.Errorf("fetch schema: status %d: %s", resp.StatusCode, strings.TrimSpace(string(message)))
	}

	var result Catalog
	if err := json.NewDecoder(limited).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode schema: %w", err)
	}
	if result.Tables == nil {
		return nil, fmt.Errorf("decode schema: response has no tables")
	}
	for name, table := range result.Tables {
		if table.Name == "" {
			table.Name = name
		}
		if table.Fields == nil {
			table.Fields = map[string]Field{}
		}
		result.Tables[name] = table
	}
	properties, err := c.loadProperties(ctx)
	if err != nil {
		return nil, err
	}
	result.Properties = properties
	return &result, nil
}

type propertyPage struct {
	Next    *string    `json:"next"`
	Results []Property `json:"results"`
}

type propertyLoadResult struct {
	namespace  string
	properties []Property
	err        error
}

func (c *Client) loadProperties(ctx context.Context) (map[string][]Property, error) {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	results := make(chan propertyLoadResult, len(propertyNamespaces))
	for _, namespace := range propertyNamespaces {
		go func() {
			properties, err := c.loadPropertyNamespace(ctx, namespace)
			results <- propertyLoadResult{namespace: namespace, properties: properties, err: err}
		}()
	}

	properties := make(map[string][]Property, len(propertyNamespaces))
	for range propertyNamespaces {
		loaded := <-results
		if loaded.err != nil {
			cancel()
			return nil, loaded.err
		}
		properties[loaded.namespace] = loaded.properties
	}
	return properties, nil
}

func (c *Client) loadPropertyNamespace(ctx context.Context, namespace string) ([]Property, error) {
	propertyType, groupTypeIndex, _ := strings.Cut(namespace, ":")
	endpoint := c.baseURL.JoinPath("api", "projects", c.projectID, "property_definitions")
	query := endpoint.Query()
	query.Set("type", propertyType)
	query.Set("exclude_restricted", "true")
	query.Set("limit", "1000")
	if groupTypeIndex != "" {
		query.Set("group_type_index", groupTypeIndex)
	}
	endpoint.RawQuery = query.Encode()

	properties := make([]Property, 0)
	for {
		page, next, err := c.loadPropertyPage(ctx, endpoint)
		if err != nil {
			return nil, fmt.Errorf("load %s properties: %w", namespace, err)
		}
		properties = append(properties, page...)
		if next == nil {
			break
		}
		endpoint = next
	}
	return properties, nil
}

func (c *Client) loadPropertyPage(ctx context.Context, endpoint *url.URL) ([]Property, *url.URL, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint.String(), nil)
	if err != nil {
		return nil, nil, fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("fetch page: %w", err)
	}
	defer resp.Body.Close()
	limited := io.LimitReader(resp.Body, 64<<20)
	if resp.StatusCode != http.StatusOK {
		message, _ := io.ReadAll(io.LimitReader(limited, 4096))
		return nil, nil, fmt.Errorf("status %d: %s", resp.StatusCode, strings.TrimSpace(string(message)))
	}
	var page propertyPage
	if err := json.NewDecoder(limited).Decode(&page); err != nil {
		return nil, nil, fmt.Errorf("decode page: %w", err)
	}
	if page.Next == nil {
		return page.Results, nil, nil
	}
	next, err := url.Parse(*page.Next)
	if err != nil {
		return nil, nil, fmt.Errorf("parse next page: %w", err)
	}
	next = endpoint.ResolveReference(next)
	if next.Scheme != c.baseURL.Scheme || next.Host != c.baseURL.Host {
		return nil, nil, fmt.Errorf("next page changed PostHog origin")
	}
	return page.Results, next, nil
}
