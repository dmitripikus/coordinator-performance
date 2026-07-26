package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"time"
)

const (
	HeaderInferenceType  = "X-Inference-Type"
	InferenceTypePrefill = "prefill"
	InferenceTypeDecode  = "decode"
)

var (
	inferenceGatewayURL = "http://10.16.1.178:80"
	transport           = &http.Transport{
		MaxIdleConns:        10000,
		MaxIdleConnsPerHost: 2000,
		IdleConnTimeout:     600 * time.Second,
		DisableCompression:  true,
	}
	httpClient = &http.Client{
		Transport: transport,
		Timeout:   0,
	}
	decodeProxy *httputil.ReverseProxy
)

type KVTransferParams struct {
	DoRemoteDecode  *bool  `json:"do_remote_decode,omitempty"`
	DoRemotePrefill *bool  `json:"do_remote_prefill,omitempty"`
	RemoteBlockIDs  []int  `json:"remote_block_ids,omitempty"`
	RemoteEngineID  string `json:"remote_engine_id,omitempty"`
	RemoteHost      string `json:"remote_host,omitempty"`
	RemotePort      int    `json:"remote_port,omitempty"`
	RemoteRequestID string `json:"remote_request_id,omitempty"`
	TpSize          int    `json:"tp_size,omitempty"`
}

type FastInferenceRequest map[string]json.RawMessage

func boolPtr(b bool) *bool { return &b }

func main() {
	if urlStr := os.Getenv("INFERENCE_GATEWAY_URL"); urlStr != "" {
		if !strings.HasPrefix(urlStr, "http://") && !strings.HasPrefix(urlStr, "https://") {
			urlStr = "http://" + urlStr
		}
		inferenceGatewayURL = urlStr
	}
	targetURL, err := url.Parse(inferenceGatewayURL)
	if err != nil {
		log.Fatalf("Invalid gateway URL: %v", err)
	}
	decodeProxy = httputil.NewSingleHostReverseProxy(targetURL)
	decodeProxy.Transport = transport
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("OK"))
	})
	http.HandleFunc("/v1/chat/completions", func(w http.ResponseWriter, r *http.Request) {
		handleInference(w, r, "/v1/chat/completions")
	})
	http.HandleFunc("/v1/completions", func(w http.ResponseWriter, r *http.Request) {
		handleInference(w, r, "/v1/completions")
	})
	log.Printf("Starting High-Performance Proxy Service on port %s", port)
	log.Printf("Upstream inference gateway URL: %s", inferenceGatewayURL)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("failed to start server: %v", err)
	}
}

func handleInference(w http.ResponseWriter, r *http.Request, path string) {
	if r.Method != http.MethodPost {
		http.Error(w, "Only POST method is allowed", http.StatusMethodNotAllowed)
		return
	}
	bodyBytes, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "failed to read request body", http.StatusInternalServerError)
		return
	}
	defer r.Body.Close()
	var originalReqBody FastInferenceRequest
	if err := json.Unmarshal(bodyBytes, &originalReqBody); err != nil {
		http.Error(w, "failed to decode request body", http.StatusBadRequest)
		return
	}
	ctx := r.Context()
	kvParams, err := doPrefill(ctx, originalReqBody, r.Header, path)
	if err != nil {
		if ctx.Err() == context.Canceled {
			log.Printf("Client disconnected during prefill request")
			return
		}
		log.Printf("Prefill request failed: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	doDecodeViaProxy(ctx, originalReqBody, kvParams, w, r, path)
}

func doPrefill(ctx context.Context, reqBody FastInferenceRequest, headers http.Header, path string) (*KVTransferParams, error) {
	prefillReqBody := make(FastInferenceRequest, len(reqBody)+3)
	for k, v := range reqBody {
		prefillReqBody[k] = v
	}
	prefillReqBody["stream"] = json.RawMessage(`false`)
	delete(prefillReqBody, "stream_options")
	prefillReqBody["max_tokens"] = json.RawMessage(`1`)
	prefillReqBody["max_completion_tokens"] = json.RawMessage(`1`)
	kvParamsObj := KVTransferParams{
		DoRemoteDecode:  boolPtr(true),
		DoRemotePrefill: boolPtr(false),
	}
	kvBytes, _ := json.Marshal(kvParamsObj)
	prefillReqBody["kv_transfer_params"] = json.RawMessage(kvBytes)
	prefillReqBytes, err := json.Marshal(prefillReqBody)
	if err != nil {
		return nil, err
	}
	urlStr := inferenceGatewayURL + path
	prefillReq, err := http.NewRequestWithContext(ctx, http.MethodPost, urlStr, bytes.NewReader(prefillReqBytes))
	if err != nil {
		return nil, err
	}
	prefillReq.Header = headers.Clone()
	prefillReq.Header.Set(HeaderInferenceType, InferenceTypePrefill)
	prefillReq.Header.Set("Content-Type", "application/json")
	resp, err := httpClient.Do(prefillReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	respBodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("prefill request failed with status %d", resp.StatusCode)
	}
	var prefillerResponse map[string]json.RawMessage
	if err := json.Unmarshal(respBodyBytes, &prefillerResponse); err != nil {
		return nil, fmt.Errorf("failed to parse prefill response: %w", err)
	}
	var kvParams KVTransferParams
	if kvMapBytes, ok := prefillerResponse["kv_transfer_params"]; ok && len(kvMapBytes) > 0 {
		_ = json.Unmarshal(kvMapBytes, &kvParams)
	} else {
		log.Printf("warning: missing 'kv_transfer_params' field in prefiller response")
		return nil, nil
	}
	return &kvParams, nil
}

func doDecodeViaProxy(ctx context.Context, reqBody FastInferenceRequest, kvParams *KVTransferParams, w http.ResponseWriter, originalReq *http.Request, path string) {
	decodeReqBody := make(FastInferenceRequest, len(reqBody)+1)
	for k, v := range reqBody {
		decodeReqBody[k] = v
	}
	if kvParams != nil {
		kvBytes, _ := json.Marshal(kvParams)
		decodeReqBody["kv_transfer_params"] = json.RawMessage(kvBytes)
	}
	decodeReqBytes, err := json.Marshal(decodeReqBody)
	if err != nil {
		http.Error(w, "failed to create decode request body", http.StatusInternalServerError)
		return
	}
	decodeReq := originalReq.Clone(ctx)
	decodeReq.URL.Path = path
	decodeReq.Body = io.NopCloser(bytes.NewReader(decodeReqBytes))
	decodeReq.ContentLength = int64(len(decodeReqBytes))
	decodeReq.Header.Set(HeaderInferenceType, InferenceTypeDecode)
	decodeReq.Header.Set("Content-Type", "application/json")
	decodeProxy.ServeHTTP(w, decodeReq)
}
