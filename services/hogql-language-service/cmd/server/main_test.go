package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/completion"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/serviceauth"
)

func TestAutocompleteUsesOnlyRequestedTeamAndUserCatalog(t *testing.T) {
	s := &server{catalogs: catalog.NewRegistry(10, time.Hour), auth: serviceauth.New(nil, true)}
	handler := s.handler()
	putCatalogForTest(t, handler, 1, 10, "revision-one", "orders")
	putCatalogForTest(t, handler, 1, 20, "revision-two", "accounts")
	putCatalogForTest(t, handler, 2, 10, "revision-three", "invoices")

	for _, test := range []struct {
		teamID   int64
		userID   int64
		revision string
		table    string
	}{
		{teamID: 1, userID: 10, revision: "revision-one", table: "orders"},
		{teamID: 1, userID: 20, revision: "revision-two", table: "accounts"},
		{teamID: 2, userID: 10, revision: "revision-three", table: "invoices"},
	} {
		body := `{"teamId":` + strconv.FormatInt(test.teamID, 10) + `,"userId":` + strconv.FormatInt(test.userID, 10) + `,"query":"SELECT * FROM "}`
		request := httptest.NewRequest(http.MethodPost, "/autocomplete", strings.NewReader(body))
		request.Header.Set("Content-Type", "application/json")
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		if response.Code != http.StatusOK {
			t.Fatalf("autocomplete returned %d: %s", response.Code, response.Body.String())
		}
		var result completionResponse
		if err := json.NewDecoder(response.Body).Decode(&result); err != nil {
			t.Fatal(err)
		}
		if result.CatalogRevision != test.revision || !hasSuggestion(result.Suggestions, test.table) {
			t.Fatalf("unexpected response for team %d user %d: %#v", test.teamID, test.userID, result)
		}
		for _, otherTable := range []string{"orders", "accounts", "invoices"} {
			if otherTable != test.table && hasSuggestion(result.Suggestions, otherTable) {
				t.Fatalf("%s leaked into team %d user %d", otherTable, test.teamID, test.userID)
			}
		}
	}
}

func TestAutocompleteRequiresKnownTeamAndUser(t *testing.T) {
	s := &server{catalogs: catalog.NewRegistry(10, time.Hour), auth: serviceauth.New(nil, true)}
	for _, test := range []struct {
		path   string
		body   string
		status int
	}{
		{path: "/autocomplete", body: `{"teamId":1,"query":"SELECT "}`, status: http.StatusBadRequest},
		{path: "/autocomplete", body: `{"userId":10,"query":"SELECT "}`, status: http.StatusBadRequest},
		{path: "/validate", body: `{"teamId":1,"query":"SELECT 1"}`, status: http.StatusBadRequest},
		{path: "/validate", body: `{"userId":10,"query":"SELECT 1"}`, status: http.StatusBadRequest},
		{path: "/autocomplete", body: `{"teamId":1,"userId":10,"query":"SELECT "}`, status: http.StatusNotFound},
	} {
		request := httptest.NewRequest(http.MethodPost, test.path, strings.NewReader(test.body))
		response := httptest.NewRecorder()
		s.handler().ServeHTTP(response, request)
		if response.Code != test.status {
			t.Fatalf("expected %d, got %d: %s", test.status, response.Code, response.Body.String())
		}
	}
}

func putCatalogForTest(t *testing.T, handler http.Handler, teamID, userID int64, revision, table string) {
	t.Helper()
	body := `{"revision":"` + revision + `","catalog":{"tables":{"` + table + `":{"name":"` + table + `","type":"warehouse","fields":{}}},"properties":{}}}`
	path := "/teams/" + strconv.FormatInt(teamID, 10) + "/users/" + strconv.FormatInt(userID, 10) + "/catalog"
	request := httptest.NewRequest(http.MethodPut, path, strings.NewReader(body))
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("catalog upload returned %d: %s", response.Code, response.Body.String())
	}
}

func hasSuggestion(suggestions []completion.Suggestion, label string) bool {
	for _, suggestion := range suggestions {
		if suggestion.Label == label {
			return true
		}
	}
	return false
}
