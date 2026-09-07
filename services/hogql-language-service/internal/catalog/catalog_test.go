package catalog

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestClientLoadsVisibleSchema(t *testing.T) {
	var server *httptest.Server
	server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("Authorization"); got != "Bearer secret" {
			t.Fatalf("authorization = %q", got)
		}
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/api/projects/7/query" {
			_, _ = w.Write([]byte(`{"tables":{"orders":{"id":"1","name":"orders","type":"data_warehouse","fields":{"order_id":{"name":"order_id","type":"string","hogql_value":"order_id","schema_valid":true}}}},"joins":[]}`))
			return
		}
		if r.URL.Query().Get("exclude_restricted") != "true" {
			t.Errorf("property request did not exclude restricted properties: %s", r.URL.RawQuery)
		}
		if r.URL.Query().Get("type") == "event" {
			if r.URL.Query().Get("offset") == "" {
				_, _ = fmt.Fprintf(w, `{"next":%q,"results":[{"name":"$geo_city","property_type":"String"}]}`, server.URL+r.URL.Path+"?type=event&exclude_restricted=true&limit=1000&offset=1000")
				return
			}
			_, _ = w.Write([]byte(`{"next":null,"results":[{"name":"$geo_country","property_type":"String"}]}`))
			return
		}
		_, _ = fmt.Fprint(w, `{"next":null,"results":[]}`)
	}))
	defer server.Close()

	client, err := NewClient(server.URL, "7", "secret", server.Client())
	if err != nil {
		t.Fatal(err)
	}
	result, err := client.Load(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if result.Tables["orders"].Fields["order_id"].Name != "order_id" {
		t.Fatalf("unexpected catalog: %#v", result)
	}
	if len(result.Properties) != 8 || len(result.Properties["event"]) != 2 || result.Properties["event"][1].Name != "$geo_country" {
		t.Fatalf("unexpected properties: %#v", result.Properties)
	}
}
