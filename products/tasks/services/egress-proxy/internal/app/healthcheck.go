package app

import (
	"context"
	"errors"
	"net/http"
	"time"
)

func CheckHealth(ctx context.Context, mode, configPath, check string) error {
	if check != "live" && check != "ready" {
		return errors.New("health check must be live or ready")
	}
	var address string
	switch mode {
	case "proxy":
		config, err := LoadProxyConfig(configPath)
		if err != nil {
			return err
		}
		address = config.AdminAddress
	case "relay":
		config, err := LoadRelayConfig(configPath)
		if err != nil {
			return err
		}
		address = config.AdminAddress
	default:
		return errors.New("unknown service mode")
	}
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://"+address+"/"+check+"z", nil)
	if err != nil {
		return errors.New("invalid health check address")
	}
	client := http.Client{
		Transport:     &http.Transport{DisableKeepAlives: true},
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse },
	}
	response, err := client.Do(request)
	if err != nil {
		return errors.New("health endpoint unavailable")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusNoContent {
		return errors.New("health endpoint rejected check")
	}
	return nil
}
