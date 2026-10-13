package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const (
	DefaultBaseUrl = "http://127.0.0.1:8766"
	MaxIconBytes   = 512 * 1024
)

var IconMime = map[string]string{
	".png":  "image/png",
	".jpg":  "image/jpeg",
	".jpeg": "image/jpeg",
	".gif":  "image/gif",
	".svg":  "image/svg+xml",
}

func NormalizeBaseUrl(value string) string {
	v := strings.TrimSpace(value)
	if v == "" {
		return DefaultBaseUrl
	}
	u, err := url.Parse(v)
	if err != nil {
		return DefaultBaseUrl
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return DefaultBaseUrl
	}
	if u.Host == "" {
		return DefaultBaseUrl
	}
	return fmt.Sprintf("%s://%s", u.Scheme, u.Host)
}

func ReadIconFile(filePath string) (string, error) {
	ext := strings.ToLower(filepath.Ext(filePath))
	mime, ok := IconMime[ext]
	if !ok {
		return "", fmt.Errorf("unsupported icon extension: %s", ext)
	}
	info, err := os.Stat(filePath)
	if err != nil {
		return "", err
	}
	if info.IsDir() || info.Size() > MaxIconBytes {
		return "", fmt.Errorf("invalid icon file or size exceeds 512KB")
	}
	data, err := os.ReadFile(filePath)
	if err != nil {
		return "", err
	}
	encoded := base64.StdEncoding.EncodeToString(data)
	return fmt.Sprintf("data:%s;base64,%s", mime, encoded), nil
}

func CryptoUUID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	b[6] = (b[6] & 0x0f) | 0x40 // Version 4
	b[8] = (b[8] & 0x3f) | 0x80 // Variant RFC4122
	return fmt.Sprintf("%s-%s-%s-%s-%s",
		hex.EncodeToString(b[0:4]),
		hex.EncodeToString(b[4:6]),
		hex.EncodeToString(b[6:8]),
		hex.EncodeToString(b[8:10]),
		hex.EncodeToString(b[10:16]))
}

type ContextEntry struct {
	Control   string
	Settings  KeySettings
	LastImage string
}

type StreamDeckEvent struct {
	Event   string          `json:"event"`
	Action  string          `json:"action,omitempty"`
	Context string          `json:"context,omitempty"`
	Payload json.RawMessage `json:"payload,omitempty"`
}

type DeckPayload struct {
	Settings KeySettings `json:"settings"`
}

type DeckGlobalPayload struct {
	Settings struct {
		DartsUrl string `json:"dartsUrl"`
	} `json:"settings"`
}

type OutgoingMessage struct {
	Event   string `json:"event"`
	Context string `json:"context,omitempty"`
	Payload any    `json:"payload,omitempty"`
}

type PluginOptions struct {
	Send         func(msg any)
	HTTPClient   *http.Client
	Now          func() time.Time
	UUIDGen      func() string
	ReadIcon     func(path string) (string, error)
	SchedulePoll func(delay time.Duration, fn func()) func()
}

type DartsPlugin struct {
	Send         func(msg any)
	HTTPClient   *http.Client
	Now          func() time.Time
	UUIDGen      func() string
	ReadIcon     func(path string) (string, error)
	scheduleFunc func(delay time.Duration, fn func()) func()

	mu        sync.Mutex
	baseURL   string
	model     *Model
	contexts  map[string]*ContextEntry
	iconCache map[string]string
	cancelTimer func()
	polling   bool
	repoll    bool
	running   bool
}

func NewDartsPlugin(opts PluginOptions) *DartsPlugin {
	send := opts.Send
	if send == nil {
		send = func(msg any) {}
	}
	client := opts.HTTPClient
	if client == nil {
		client = &http.Client{Timeout: RequestTimeout}
	}
	now := opts.Now
	if now == nil {
		now = time.Now
	}
	uuidGen := opts.UUIDGen
	if uuidGen == nil {
		uuidGen = CryptoUUID
	}
	readIcon := opts.ReadIcon
	if readIcon == nil {
		readIcon = ReadIconFile
	}
	scheduleFunc := opts.SchedulePoll
	if scheduleFunc == nil {
		scheduleFunc = func(delay time.Duration, fn func()) func() {
			t := time.AfterFunc(delay, fn)
			return func() { t.Stop() }
		}
	}

	return &DartsPlugin{
		Send:         send,
		HTTPClient:   client,
		Now:          now,
		UUIDGen:      uuidGen,
		ReadIcon:     readIcon,
		scheduleFunc: scheduleFunc,
		baseURL:      DefaultBaseUrl,
		model:        CreateModel(),
		contexts:     make(map[string]*ContextEntry),
		iconCache:    make(map[string]string),
	}
}

func (p *DartsPlugin) Start() {
	p.mu.Lock()
	p.running = true
	p.mu.Unlock()

	p.renderAll()
	p.RequestSync()
}

func (p *DartsPlugin) Stop() {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.running = false
	if p.cancelTimer != nil {
		p.cancelTimer()
		p.cancelTimer = nil
	}
}

func (p *DartsPlugin) Log(message string) {
	p.Send(OutgoingMessage{
		Event: "logMessage",
		Payload: map[string]string{
			"message": fmt.Sprintf("[DARTS] %s", message),
		},
	})
}

func (p *DartsPlugin) HandleDeckMessage(raw []byte) {
	var msg StreamDeckEvent
	if err := json.Unmarshal(raw, &msg); err != nil {
		return
	}

	switch msg.Event {
	case "willAppear":
		control, ok := Actions[msg.Action]
		if !ok {
			return
		}
		var payload DeckPayload
		if len(msg.Payload) > 0 {
			_ = json.Unmarshal(msg.Payload, &payload)
		}
		p.mu.Lock()
		p.contexts[msg.Context] = &ContextEntry{
			Control:  control,
			Settings: payload.Settings,
		}
		p.mu.Unlock()
		p.renderContext(msg.Context)
		p.RequestSync()

	case "willDisappear":
		p.mu.Lock()
		delete(p.contexts, msg.Context)
		p.mu.Unlock()

	case "didReceiveSettings":
		p.mu.Lock()
		entry, ok := p.contexts[msg.Context]
		if !ok {
			p.mu.Unlock()
			return
		}
		var payload DeckPayload
		if len(msg.Payload) > 0 {
			_ = json.Unmarshal(msg.Payload, &payload)
		}
		entry.Settings = payload.Settings
		entry.LastImage = ""
		p.iconCache = make(map[string]string)
		p.mu.Unlock()
		p.renderContext(msg.Context)

	case "didReceiveGlobalSettings":
		var payload DeckGlobalPayload
		if len(msg.Payload) > 0 {
			_ = json.Unmarshal(msg.Payload, &payload)
		}
		p.mu.Lock()
		p.baseURL = NormalizeBaseUrl(payload.Settings.DartsUrl)
		p.mu.Unlock()
		p.RequestSync()

	case "keyDown":
		go p.pressKey(msg.Context)

	case "systemDidWakeUp":
		p.RequestSync()
	}
}

func (p *DartsPlugin) RequestSync() {
	p.mu.Lock()
	if !p.running {
		p.mu.Unlock()
		return
	}
	if p.polling {
		p.repoll = true
		p.mu.Unlock()
		return
	}
	p.schedulePollLocked(0)
	p.mu.Unlock()
}

func (p *DartsPlugin) schedulePollLocked(delay time.Duration) {
	if p.cancelTimer != nil {
		p.cancelTimer()
		p.cancelTimer = nil
	}
	p.cancelTimer = p.scheduleFunc(delay, func() {
		p.Poll()
	})
}

func (p *DartsPlugin) Poll() {
	p.mu.Lock()
	if !p.running {
		p.mu.Unlock()
		return
	}
	if p.polling {
		p.repoll = true
		p.mu.Unlock()
		return
	}
	p.polling = true
	baseURL := p.baseURL
	p.mu.Unlock()

	// Perform HTTP GET without holding lock
	ctx, cancel := context.WithTimeout(context.Background(), RequestTimeout)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, fmt.Sprintf("%s/api/ui-state", baseURL), nil)
	var snapshot *UiStateSnapshot
	var getErr error
	if err == nil {
		req.Header.Set("Cache-Control", "no-store")
		resp, rErr := p.HTTPClient.Do(req)
		if rErr != nil {
			getErr = rErr
		} else {
			defer resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				var s UiStateSnapshot
				bodyBytes, _ := io.ReadAll(resp.Body)
				if uErr := json.Unmarshal(bodyBytes, &s); uErr == nil {
					snapshot = &s
				} else {
					getErr = uErr
				}
			} else {
				getErr = fmt.Errorf("HTTP %d", resp.StatusCode)
			}
		}
	} else {
		getErr = err
	}
	cancel()

	p.mu.Lock()
	p.polling = false
	if getErr != nil || snapshot == nil {
		p.model.MarkOffline()
	} else {
		p.model.ApplySnapshot(snapshot)
	}

	// Check pending timeout
	now := p.Now()
	pending := p.model.PendingCommand
	var timeoutAlertControl string
	var timeoutMsg string
	if pending != nil && p.model.ExpirePending(now) {
		timeoutMsg = fmt.Sprintf("%s (%s) was not confirmed by the live map", pending.Command, pending.RequestId)
		timeoutAlertControl = pending.Control
	}

	p.mu.Unlock()

	if timeoutMsg != "" {
		p.Log(timeoutMsg)
		p.alertControl(timeoutAlertControl)
	}

	p.renderAll()

	p.mu.Lock()
	if !p.running {
		p.mu.Unlock()
		return
	}
	if p.repoll {
		p.repoll = false
		p.schedulePollLocked(0)
	} else if p.model.PendingCommand != nil {
		p.schedulePollLocked(PendingPollInterval)
	} else if p.model.ConnectionState == "offline" {
		p.schedulePollLocked(OfflinePollInterval)
	} else {
		p.schedulePollLocked(PollInterval)
	}
	p.mu.Unlock()
}

func (p *DartsPlugin) alertControl(control string) {
	p.mu.Lock()
	var targets []string
	for ctx, entry := range p.contexts {
		if entry.Control == control {
			targets = append(targets, ctx)
		}
	}
	p.mu.Unlock()

	for _, ctx := range targets {
		p.Send(OutgoingMessage{
			Event:   "showAlert",
			Context: ctx,
		})
	}
}

func (p *DartsPlugin) pressKey(contextKey string) {
	p.mu.Lock()
	entry, ok := p.contexts[contextKey]
	if !ok {
		p.mu.Unlock()
		return
	}
	now := p.Now()
	begin := p.model.BeginCommand(entry.Control, now, p.UUIDGen)
	if !begin.Ok {
		p.mu.Unlock()
		if begin.Reason != "pending" {
			p.Send(OutgoingMessage{
				Event:   "showAlert",
				Context: contextKey,
			})
		}
		p.RequestSync()
		return
	}
	baseURL := p.baseURL
	ctrl := entry.Control
	p.mu.Unlock()

	p.renderAll()

	// Send POST /api/ui-command
	postBody, _ := json.Marshal(map[string]string{
		"command":    begin.Command,
		"request_id": begin.RequestId,
	})

	ctx, cancel := context.WithTimeout(context.Background(), RequestTimeout)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, fmt.Sprintf("%s/api/ui-command", baseURL), bytes.NewReader(postBody))
	var postErr error
	if err == nil {
		req.Header.Set("Content-Type", "application/json")
		resp, rErr := p.HTTPClient.Do(req)
		if rErr != nil {
			postErr = rErr
		} else {
			defer resp.Body.Close()
			if resp.StatusCode != http.StatusOK {
				postErr = fmt.Errorf("HTTP %d", resp.StatusCode)
			}
		}
	} else {
		postErr = err
	}
	cancel()

	if postErr != nil {
		p.mu.Lock()
		failNow := p.Now()
		if p.model.FailCommand(begin.RequestId, failNow) {
			p.mu.Unlock()
			p.Log(fmt.Sprintf("%s failed: %v", begin.Command, postErr))
			p.alertControl(ctrl)
		} else {
			p.mu.Unlock()
		}
	}

	p.renderAll()
	p.RequestSync()
}

func (p *DartsPlugin) iconFor(iconPath string) string {
	if iconPath == "" {
		return ""
	}
	p.mu.Lock()
	if cached, ok := p.iconCache[iconPath]; ok {
		p.mu.Unlock()
		return cached
	}
	p.mu.Unlock()

	uri, err := p.ReadIcon(iconPath)
	if err != nil {
		p.Log(fmt.Sprintf("icon override not loaded (%s): %v", iconPath, err))
		uri = ""
	}

	p.mu.Lock()
	p.iconCache[iconPath] = uri
	p.mu.Unlock()
	return uri
}

func (p *DartsPlugin) renderContext(contextKey string) {
	p.mu.Lock()
	entry, ok := p.contexts[contextKey]
	if !ok {
		p.mu.Unlock()
		return
	}
	now := p.Now()
	status := p.model.KeyStatus(entry.Control, now)
	settings := entry.Settings
	p.mu.Unlock()

	normalized := NormalizeSettings(entry.Control, settings)
	image := p.iconFor(normalized.ImagePath(status))
	if image == "" {
		iconUri := p.iconFor(normalized.Icon)
		image = SvgToImage(RenderKeySvg(entry.Control, status, settings, iconUri))
	}

	p.mu.Lock()
	entry, ok = p.contexts[contextKey]
	if !ok || entry.LastImage == image {
		p.mu.Unlock()
		return
	}
	entry.LastImage = image
	p.mu.Unlock()

	p.Send(OutgoingMessage{
		Event:   "setImage",
		Context: contextKey,
		Payload: map[string]any{
			"image":  image,
			"target": 0,
		},
	})
}

func (p *DartsPlugin) renderAll() {
	p.mu.Lock()
	keys := make([]string, 0, len(p.contexts))
	for k := range p.contexts {
		keys = append(keys, k)
	}
	p.mu.Unlock()

	for _, k := range keys {
		p.renderContext(k)
	}
}
