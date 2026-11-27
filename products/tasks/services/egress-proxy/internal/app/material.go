package app

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"time"
)

func certificate(certFile, keyFile string) (tls.Certificate, error) {
	certPEM, err := readFile(certFile)
	if err != nil {
		return tls.Certificate{}, err
	}
	keyPEM, err := readFile(keyFile)
	if err != nil {
		return tls.Certificate{}, err
	}
	cert, err := tls.X509KeyPair(certPEM, keyPEM)
	if err != nil {
		return tls.Certificate{}, errors.New("invalid TLS certificate or key")
	}
	if cert.Leaf == nil {
		cert.Leaf, err = x509.ParseCertificate(cert.Certificate[0])
	}
	if err != nil || !certificateActive(cert.Leaf) {
		return tls.Certificate{}, errors.New("TLS certificate is not active")
	}
	return cert, nil
}

func certificateActive(cert *x509.Certificate) bool {
	now := time.Now()
	return cert != nil && !now.Before(cert.NotBefore) && now.Before(cert.NotAfter)
}

func verifyClientCertificate(cert tls.Certificate, caFile string) error {
	if caFile == "" {
		return errors.New("relay renewal requires a client CA bundle")
	}
	trusted, err := roots(caFile)
	if err != nil {
		return err
	}
	intermediates := x509.NewCertPool()
	for _, raw := range cert.Certificate[1:] {
		intermediate, err := x509.ParseCertificate(raw)
		if err != nil {
			return errors.New("invalid relay certificate chain")
		}
		intermediates.AddCert(intermediate)
	}
	if _, err := cert.Leaf.Verify(x509.VerifyOptions{
		Roots: trusted, Intermediates: intermediates, KeyUsages: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}); err != nil {
		return errors.New("relay certificate is not trusted for client authentication")
	}
	return nil
}

func roots(path string) (*x509.CertPool, error) {
	bundle, err := loadRoots(path)
	return bundle.pool, err
}

type rootBundle struct {
	pool    *x509.CertPool
	expires time.Time
}

func loadRoots(path string) (rootBundle, error) {
	if path == "" {
		return rootBundle{}, nil
	}
	data, err := readFile(path)
	if err != nil {
		return rootBundle{}, err
	}
	bundle := rootBundle{pool: x509.NewCertPool()}
	for len(data) > 0 {
		var block *pem.Block
		block, data = pem.Decode(data)
		if block == nil {
			break
		}
		if block.Type != "CERTIFICATE" || len(block.Headers) != 0 {
			continue
		}
		cert, err := x509.ParseCertificate(block.Bytes)
		if err != nil {
			continue
		}
		bundle.pool.AddCert(cert)
		if bundle.expires.IsZero() || cert.NotAfter.Before(bundle.expires) {
			bundle.expires = cert.NotAfter
		}
	}
	if bundle.expires.IsZero() {
		return rootBundle{}, errors.New("invalid CA bundle")
	}
	return bundle, nil
}
