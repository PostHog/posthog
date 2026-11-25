package app

import (
	"crypto/tls"
	"crypto/x509"
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
	if path == "" {
		return nil, nil
	}
	data, err := readFile(path)
	if err != nil {
		return nil, err
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(data) {
		return nil, errors.New("invalid CA bundle")
	}
	return pool, nil
}
