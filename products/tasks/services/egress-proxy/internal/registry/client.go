package registry

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
)

const (
	serviceAudience  = "posthog:agent_egress_registry"
	maxResponseBytes = 16 << 10
)

var (
	regionPattern = regexp.MustCompile(`^[a-zA-Z0-9_-]{1,32}$`)
	uuidPattern   = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
)

type Config struct {
	BaseURL    string
	Region     string
	SigningKey string
	Timeout    time.Duration
	HTTPClient *http.Client
}

type Client struct {
	baseURL    string
	region     string
	signingKey []byte
	timeout    time.Duration
	http       http.Client
}

func New(config Config) (*Client, error) {
	endpoint, err := url.Parse(config.BaseURL)
	if err != nil || endpoint.Scheme != "https" || endpoint.Hostname() == "" || endpoint.User != nil ||
		endpoint.Opaque != "" || endpoint.RawQuery != "" || endpoint.ForceQuery || endpoint.Fragment != "" ||
		(endpoint.Path != "" && endpoint.Path != "/") || !regionPattern.MatchString(config.Region) ||
		len(config.SigningKey) < 32 || config.Timeout <= 0 {
		return nil, errors.New("invalid registry client configuration")
	}
	client := http.Client{}
	if config.HTTPClient != nil {
		client = *config.HTTPClient
	} else {
		transport := http.DefaultTransport.(*http.Transport).Clone()
		transport.Proxy = nil
		client.Transport = transport
	}
	client.CheckRedirect = func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }
	client.Jar = nil
	return &Client{
		baseURL: strings.TrimSuffix(endpoint.String(), "/"), region: config.Region,
		signingKey: []byte(config.SigningKey), timeout: config.Timeout, http: client,
	}, nil
}

func (c *Client) Lookup(ctx context.Context, lookup identity.LookupRequest) (identity.Registration, error) {
	if lookup.TeamID <= 0 || !uuidPattern.MatchString(lookup.RunID) || !uuidPattern.MatchString(lookup.ExecutionID) {
		return identity.Registration{}, identity.ErrUnauthorized
	}
	ctx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()
	if ctx.Err() != nil {
		return identity.Registration{}, identity.ErrUnavailable
	}
	now := time.Now().Unix()
	token, err := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"aud": serviceAudience, "sub": lookup.RunID, "team_id": lookup.TeamID,
		"execution_id": lookup.ExecutionID, "region": c.region, "operation": "lookup",
		"iat": now, "exp": now + 30,
	}).SignedString(c.signingKey)
	if err != nil {
		return identity.Registration{}, identity.ErrUnavailable
	}
	endpoint := fmt.Sprintf("%s/api/projects/%d/internal/agent_egress/runs/%s/executions/%s",
		c.baseURL, lookup.TeamID, lookup.RunID, lookup.ExecutionID)
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return identity.Registration{}, identity.ErrUnavailable
	}
	request.Header.Set("Authorization", "Bearer "+token)
	request.Header.Set("Accept", "application/json")
	response, err := c.http.Do(request)
	if err != nil {
		return identity.Registration{}, identity.ErrUnavailable
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		if ctx.Err() == nil {
			_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, maxResponseBytes+1))
		}
		if response.StatusCode == http.StatusNotFound {
			return identity.Registration{}, identity.ErrUnauthorized
		}
		return identity.Registration{}, identity.ErrUnavailable
	}
	if ctx.Err() != nil {
		return identity.Registration{}, identity.ErrUnavailable
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maxResponseBytes+1))
	if err != nil || ctx.Err() != nil || len(body) > maxResponseBytes {
		return identity.Registration{}, identity.ErrUnavailable
	}
	var result struct {
		identity.Registration
		Region  string `json:"region"`
		Revoked *bool  `json:"revoked"`
	}
	if err := json.Unmarshal(body, &result); err != nil || result.Region != c.region ||
		result.RunID != lookup.RunID || result.TeamID != lookup.TeamID || result.ExecutionID != lookup.ExecutionID ||
		result.ActorID <= 0 || result.ActorEpoch == 0 || result.Authority == "" ||
		result.LeaseExpiresAt.IsZero() || result.Revoked == nil {
		return identity.Registration{}, identity.ErrUnavailable
	}
	fingerprint, err := base64.RawURLEncoding.Strict().DecodeString(result.RelayKeySHA256)
	if err != nil || len(fingerprint) != 32 {
		return identity.Registration{}, identity.ErrUnavailable
	}
	if *result.Revoked {
		return identity.Registration{}, identity.ErrUnauthorized
	}
	return result.Registration, nil
}
