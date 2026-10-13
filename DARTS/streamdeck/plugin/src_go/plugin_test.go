package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"
)

type roundTripFunc func(req *http.Request) *http.Response

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return f(req), nil
}

func TestPluginScenario(t *testing.T) {
	var clockMu sync.Mutex
	clock := time.Unix(100, 0)
	now := func() time.Time {
		clockMu.Lock()
		defer clockMu.Unlock()
		return clock
	}
	advanceClock := func(d time.Duration) {
		clockMu.Lock()
		clock = clock.Add(d)
		clockMu.Unlock()
	}

	seq := 0
	uuidGen := func() string {
		seq++
		return fmt.Sprintf("uuid-%d", seq)
	}

	var sentMu sync.Mutex
	var sent []OutgoingMessage
	send := func(msg any) {
		data, _ := json.Marshal(msg)
		var out OutgoingMessage
		_ = json.Unmarshal(data, &out)
		sentMu.Lock()
		sent = append(sent, out)
		sentMu.Unlock()
	}

	var dartsMu sync.Mutex
	dartsUp := true
	dartsState := &UiStateSnapshot{
		ConnectionState: "connected",
		MapEnabled:      boolPtr(true),
		IfrEnabled:      boolPtr(false),
		VfrEnabled:      boolPtr(true),
		Revision:        intPtr(1),
	}
	var dartsCommands []map[string]string
	commandStatus := 200

	fakeClient := &http.Client{
		Transport: roundTripFunc(func(req *http.Request) *http.Response {
			dartsMu.Lock()
			defer dartsMu.Unlock()

			if !dartsUp {
				return &http.Response{
					StatusCode: http.StatusServiceUnavailable,
					Body:       io.NopCloser(strings.NewReader("down")),
					Header:     make(http.Header),
				}
			}

			if strings.HasSuffix(req.URL.Path, "/api/ui-state") {
				body, _ := json.Marshal(dartsState)
				return &http.Response{
					StatusCode: http.StatusOK,
					Body:       io.NopCloser(bytes.NewReader(body)),
					Header:     make(http.Header),
				}
			}

			if strings.HasSuffix(req.URL.Path, "/api/ui-command") {
				var cmd map[string]string
				body, _ := io.ReadAll(req.Body)
				_ = json.Unmarshal(body, &cmd)
				dartsCommands = append(dartsCommands, cmd)
				return &http.Response{
					StatusCode: commandStatus,
					Body:       io.NopCloser(strings.NewReader("{}")),
					Header:     make(http.Header),
				}
			}

			return &http.Response{
				StatusCode: http.StatusNotFound,
				Body:       io.NopCloser(strings.NewReader("not found")),
				Header:     make(http.Header),
			}
		}),
	}

	var timers []func()
	var timersMu sync.Mutex
	schedulePoll := func(delay time.Duration, fn func()) func() {
		timersMu.Lock()
		timers = append(timers, fn)
		timersMu.Unlock()
		return func() {}
	}
	runTimers := func() {
		timersMu.Lock()
		var fn func()
		if len(timers) > 0 {
			fn = timers[len(timers)-1]
			timers = nil
		}
		timersMu.Unlock()
		if fn != nil {
			fn()
		}
	}

	plugin := NewDartsPlugin(PluginOptions{
		Send:         send,
		HTTPClient:   fakeClient,
		Now:          now,
		UUIDGen:      uuidGen,
		SchedulePoll: schedulePoll,
		ReadIcon: func(path string) (string, error) {
			return "", fmt.Errorf("missing")
		},
	})

	lastImage := func(context string) string {
		sentMu.Lock()
		defer sentMu.Unlock()
		var img string
		for _, m := range sent {
			if m.Event == "setImage" && m.Context == context {
				if payload, ok := m.Payload.(map[string]any); ok {
					if imgVal, ok := payload["image"].(string); ok {
						img = imgVal
					}
				}
			}
		}
		return img
	}

	statusRe := regexp.MustCompile(`font-size="22">([^<]*)</text>`)
	statusOf := func(context string) string {
		img := lastImage(context)
		m := statusRe.FindStringSubmatch(img)
		if len(m) < 2 {
			return ""
		}
		return m[1]
	}

	plugin.Start()
	defer plugin.Stop()

	// Register actions
	plugin.HandleDeckMessage([]byte(`{"event":"willAppear","action":"com.pineapplecola.darts.map","context":"k-map","payload":{"settings":{}}}`))
	plugin.HandleDeckMessage([]byte(`{"event":"willAppear","action":"com.pineapplecola.darts.ifr","context":"k-ifr","payload":{"settings":{"icon":"C:/none.png"}}}`))
	plugin.HandleDeckMessage([]byte(`{"event":"willAppear","action":"com.pineapplecola.darts.vfr","context":"k-vfr","payload":{"settings":{}}}`))
	plugin.HandleDeckMessage([]byte(`{"event":"willAppear","action":"com.example.other","context":"k-other","payload":{}}`))

	if st := statusOf("k-ifr"); st != "OFFLINE" {
		t.Fatalf("expected OFFLINE, got %s", st)
	}

	// Poll DARTS
	runTimers()

	if st := statusOf("k-map"); st != "ON" {
		t.Fatalf("expected map ON, got %s", st)
	}
	if st := statusOf("k-ifr"); st != "OFF" {
		t.Fatalf("expected ifr OFF, got %s", st)
	}
	if st := statusOf("k-vfr"); st != "ON" {
		t.Fatalf("expected vfr ON, got %s", st)
	}
	if st := statusOf("k-other"); st != "" {
		t.Fatalf("expected no image for k-other, got %s", st)
	}

	// Press key
	plugin.pressKey("k-ifr")
	dartsMu.Lock()
	if len(dartsCommands) != 1 {
		t.Fatalf("expected 1 command, got %d", len(dartsCommands))
	}
	reqCmd := dartsCommands[0]
	dartsMu.Unlock()

	if reqCmd["command"] != "toggle_ifr" {
		t.Fatalf("expected toggle_ifr, got %s", reqCmd["command"])
	}
	if !strings.HasPrefix(reqCmd["request_id"], "sd-uuid-") {
		t.Fatalf("expected sd-uuid- prefix, got %s", reqCmd["request_id"])
	}

	if st := statusOf("k-ifr"); st != "WAIT" {
		t.Fatalf("expected WAIT, got %s", st)
	}

	// Confirm with snapshot
	dartsMu.Lock()
	dartsState = &UiStateSnapshot{
		ConnectionState: "connected",
		MapEnabled:      boolPtr(true),
		IfrEnabled:      boolPtr(true),
		VfrEnabled:      boolPtr(true),
		LastRequestId:   reqCmd["request_id"],
	}
	dartsMu.Unlock()

	runTimers()
	if st := statusOf("k-ifr"); st != "ON" {
		t.Fatalf("expected confirmed ON, got %s", st)
	}

	// Timeout into ERROR
	plugin.pressKey("k-map")
	if st := statusOf("k-map"); st != "WAIT" {
		t.Fatalf("expected map WAIT, got %s", st)
	}

	advanceClock(ConfirmTimeout)
	runTimers()
	if st := statusOf("k-map"); st != "ERROR" {
		t.Fatalf("expected map ERROR after timeout, got %s", st)
	}

	advanceClock(ErrorHoldDuration + time.Millisecond)
	runTimers()
	if st := statusOf("k-map"); st != "ON" {
		t.Fatalf("expected map back to ON, got %s", st)
	}

	// HTTP error on command -> immediate error
	dartsMu.Lock()
	commandStatus = 503
	dartsMu.Unlock()
	plugin.pressKey("k-map")
	if st := statusOf("k-map"); st != "ERROR" {
		t.Fatalf("expected map ERROR on 503, got %s", st)
	}
	dartsMu.Lock()
	commandStatus = 200
	dartsMu.Unlock()
	advanceClock(ErrorHoldDuration + time.Millisecond)

	// No map state
	dartsMu.Lock()
	dartsState = &UiStateSnapshot{
		ConnectionState: "no_map",
		MapEnabled:      nil,
		IfrEnabled:      nil,
		VfrEnabled:      nil,
	}
	dartsMu.Unlock()
	runTimers()
	if st := statusOf("k-map"); st != "NO MAP" {
		t.Fatalf("expected NO MAP, got %s", st)
	}

	// Pressing while NO MAP is rejected
	dartsMu.Lock()
	cmdsBefore := len(dartsCommands)
	dartsMu.Unlock()
	plugin.pressKey("k-ifr")
	dartsMu.Lock()
	if len(dartsCommands) != cmdsBefore {
		t.Fatalf("expected no command sent while NO MAP")
	}
	dartsMu.Unlock()

	// Reconnect and change settings
	dartsMu.Lock()
	dartsState = &UiStateSnapshot{
		ConnectionState: "connected",
		MapEnabled:      boolPtr(true),
		IfrEnabled:      boolPtr(true),
		VfrEnabled:      boolPtr(true),
	}
	dartsMu.Unlock()
	runTimers()
	if st := statusOf("k-ifr"); st != "ON" {
		t.Fatalf("expected ifr ON, got %s", st)
	}

	// didReceiveSettings updates label & color
	plugin.HandleDeckMessage([]byte(`{"event":"didReceiveSettings","action":"com.pineapplecola.darts.ifr","context":"k-ifr","payload":{"settings":{"label":"IFR WP","colorOn":"#123456"}}}`))
	ifrImg := lastImage("k-ifr")
	if !strings.Contains(ifrImg, `fill="#123456"`) {
		t.Fatalf("expected custom color fill in %s", ifrImg)
	}
	if !strings.Contains(ifrImg, `>IFR WP</text>`) {
		t.Fatalf("expected custom label in %s", ifrImg)
	}

	// didReceiveGlobalSettings
	plugin.HandleDeckMessage([]byte(`{"event":"didReceiveGlobalSettings","payload":{"settings":{"dartsUrl":"http://127.0.0.1:9999"}}}`))
	if plugin.baseURL != "http://127.0.0.1:9999" {
		t.Fatalf("expected baseURL http://127.0.0.1:9999, got %s", plugin.baseURL)
	}

	// willDisappear
	plugin.HandleDeckMessage([]byte(`{"event":"willDisappear","context":"k-ifr"}`))
	plugin.mu.Lock()
	_, exists := plugin.contexts["k-ifr"]
	plugin.mu.Unlock()
	if exists {
		t.Fatalf("expected k-ifr removed after willDisappear")
	}
}
