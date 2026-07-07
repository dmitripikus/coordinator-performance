// Command reqsend sends sequential OpenAI completion requests to a host and
// reports per-request timing. Optionally reuses a single TCP connection.
//
// Standalone: stdlib only, no external modules. Build with:
//   go build -o reqsend main.go
package main

import (
	"bytes"
	"crypto/rand"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

// requestID returns a random hex string for the x-request-id header.
func requestID() string {
	var b [16]byte
	rand.Read(b[:])
	return fmt.Sprintf("%x", b)
}

func main() {
	host := flag.String("host", "localhost", "destination host")
	port := flag.Int("port", 8000, "destination port")
	n := flag.Int("n", 1, "number of requests")
	reuse := flag.Bool("reuse", true, "reuse a single TCP connection")
	model := flag.String("model", "default", "model name")
	path := flag.String("path", "/v1/completions", "request path")
	flag.Parse()

	url := fmt.Sprintf("http://%s:%d%s", *host, *port, *path)
	body, _ := json.Marshal(map[string]any{
		"model":      *model,
		"prompt":     "Hi",
		"max_tokens": 16,
	})

	// reuse=false forces a fresh TCP connection per request.
	client := &http.Client{Transport: &http.Transport{DisableKeepAlives: !*reuse}}

	for i := 0; i < *n; i++ {
		id := requestID()
		req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
		if err != nil {
			fmt.Fprintf(os.Stderr, "build request: %v\n", err)
			os.Exit(1)
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("x-request-id", id)

		start := time.Now()
		resp, err := client.Do(req)
		if err != nil {
			fmt.Fprintf(os.Stderr, "%s request failed: %v\n", id, err)
			continue
		}
		io.Copy(io.Discard, resp.Body) // drain so the connection can be reused
		resp.Body.Close()
		end := time.Now()

		fmt.Printf("x-request-id=%s start=%s end=%s duration=%s status=%d\n",
			id, start.Format(time.RFC3339Nano), end.Format(time.RFC3339Nano), end.Sub(start), resp.StatusCode)
	}
}
