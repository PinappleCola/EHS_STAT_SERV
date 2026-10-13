package main

import (
	"fmt"
	"math"
	"regexp"
	"strings"
	"time"
)

type ControlSpec struct {
	Command  string
	StateKey string
	Label    string
}

var Controls = map[string]ControlSpec{
	"map": {Command: "toggle_map", StateKey: "mapEnabled", Label: "MAP"},
	"ifr": {Command: "toggle_ifr", StateKey: "ifrEnabled", Label: "IFR"},
	"vfr": {Command: "toggle_vfr", StateKey: "vfrEnabled", Label: "VFR"},
}

var Actions = map[string]string{
	"com.pineapplecola.darts.map": "map",
	"com.pineapplecola.darts.ifr": "ifr",
	"com.pineapplecola.darts.vfr": "vfr",
}

var validConnectionStates = map[string]bool{
	"connected": true,
	"offline":   true,
	"no_map":    true,
	"stale":     true,
}

const (
	PollInterval        = 1000 * time.Millisecond
	PendingPollInterval = 250 * time.Millisecond
	OfflinePollInterval = 2000 * time.Millisecond
	RequestTimeout      = 1500 * time.Millisecond
	ConfirmTimeout      = 3000 * time.Millisecond
	ErrorHoldDuration   = 1500 * time.Millisecond
)

var DefaultColors = map[string]string{
	"colorOn":      "#15803D",
	"colorOff":     "#B91C1C",
	"colorPending": "#B45309",
	"colorOffline": "#CBD5E1",
	"colorNoMap":   "#475569",
}

var StatusText = map[string]string{
	"on":      "ON",
	"off":     "OFF",
	"pending": "WAIT",
	"error":   "ERROR",
	"offline": "OFFLINE",
	"no_map":  "NO MAP",
	"stale":   "STALE",
}

var StatusColorKey = map[string]string{
	"on":      "colorOn",
	"off":     "colorOff",
	"pending": "colorPending",
	"error":   "colorPending",
	"offline": "colorOffline",
	"no_map":  "colorNoMap",
	"stale":   "colorNoMap",
}

var (
	colorRe       = regexp.MustCompile(`^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$`)
	iconDataUriRe = regexp.MustCompile(`^data:image/(?:png|jpeg|gif|svg\+xml);base64,[A-Za-z0-9+/=]+$`)
	xmlReplacer   = strings.NewReplacer(
		"&", "&amp;",
		"<", "&lt;",
		">", "&gt;",
		"'", "&apos;",
		"\"", "&quot;",
	)
)

const maxLabelLength = 10

type KeySettings struct {
	Label        string `json:"label,omitempty"`
	ColorOn      string `json:"colorOn,omitempty"`
	ColorOff     string `json:"colorOff,omitempty"`
	ColorPending string `json:"colorPending,omitempty"`
	ColorOffline string `json:"colorOffline,omitempty"`
	ColorNoMap   string `json:"colorNoMap,omitempty"`
	Icon         string `json:"icon,omitempty"`
	ImageOn      string `json:"imageOn,omitempty"`
	ImageOff     string `json:"imageOff,omitempty"`
	ImagePending string `json:"imagePending,omitempty"`
	ImageError   string `json:"imageError,omitempty"`
	ImageOffline string `json:"imageOffline,omitempty"`
	ImageNoMap   string `json:"imageNoMap,omitempty"`
	ImageStale   string `json:"imageStale,omitempty"`
}

type NormalizedSettings struct {
	Label        string
	ColorOn      string
	ColorOff     string
	ColorPending string
	ColorOffline string
	ColorNoMap   string
	Icon         string
	ImageOn      string
	ImageOff     string
	ImagePending string
	ImageError   string
	ImageOffline string
	ImageNoMap   string
	ImageStale   string
}

func (s NormalizedSettings) ImagePath(status string) string {
	switch status {
	case "on":
		return s.ImageOn
	case "off":
		return s.ImageOff
	case "pending":
		return s.ImagePending
	case "error":
		return s.ImageError
	case "offline":
		return s.ImageOffline
	case "no_map":
		return s.ImageNoMap
	case "stale":
		return s.ImageStale
	default:
		return ""
	}
}

func (s NormalizedSettings) GetColor(key string) string {
	switch key {
	case "colorOn":
		return s.ColorOn
	case "colorOff":
		return s.ColorOff
	case "colorPending":
		return s.ColorPending
	case "colorOffline":
		return s.ColorOffline
	case "colorNoMap":
		return s.ColorNoMap
	default:
		return s.ColorOffline
	}
}

func NormalizeSettings(control string, settings KeySettings) NormalizedSettings {
	trimmedLabel := strings.TrimSpace(settings.Label)
	if len(trimmedLabel) > maxLabelLength {
		trimmedLabel = trimmedLabel[:maxLabelLength]
	}
	if trimmedLabel == "" {
		if spec, ok := Controls[control]; ok {
			trimmedLabel = spec.Label
		} else {
			trimmedLabel = "?"
		}
	}

	normColor := func(val, fallback string) string {
		v := strings.TrimSpace(val)
		if colorRe.MatchString(v) {
			return v
		}
		return fallback
	}

	return NormalizedSettings{
		Label:        trimmedLabel,
		ColorOn:      normColor(settings.ColorOn, DefaultColors["colorOn"]),
		ColorOff:     normColor(settings.ColorOff, DefaultColors["colorOff"]),
		ColorPending: normColor(settings.ColorPending, DefaultColors["colorPending"]),
		ColorOffline: normColor(settings.ColorOffline, DefaultColors["colorOffline"]),
		ColorNoMap:   normColor(settings.ColorNoMap, DefaultColors["colorNoMap"]),
		Icon:         strings.TrimSpace(settings.Icon),
		ImageOn:      strings.TrimSpace(settings.ImageOn),
		ImageOff:     strings.TrimSpace(settings.ImageOff),
		ImagePending: strings.TrimSpace(settings.ImagePending),
		ImageError:   strings.TrimSpace(settings.ImageError),
		ImageOffline: strings.TrimSpace(settings.ImageOffline),
		ImageNoMap:   strings.TrimSpace(settings.ImageNoMap),
		ImageStale:   strings.TrimSpace(settings.ImageStale),
	}
}

func EscapeXml(text string) string {
	return xmlReplacer.Replace(text)
}

func TextColorForBackground(bgHex string) string {
	clean := strings.TrimPrefix(strings.TrimSpace(bgHex), "#")
	if len(clean) == 3 {
		clean = string([]byte{clean[0], clean[0], clean[1], clean[1], clean[2], clean[2]})
	}
	if len(clean) != 6 {
		return "#FFFFFF"
	}
	var r, g, b uint8
	if _, err := fmt.Sscanf(clean, "%02x%02x%02x", &r, &g, &b); err != nil {
		return "#FFFFFF"
	}
	lum := 0.299*float64(r) + 0.587*float64(g) + 0.114*float64(b)
	if lum > 160 {
		return "#0F172A"
	}
	return "#FFFFFF"
}

func RenderKeySvg(control string, status string, settings KeySettings, iconDataUri string) string {
	s := NormalizeSettings(control, settings)
	colorKey := StatusColorKey[status]
	if colorKey == "" {
		colorKey = "colorOffline"
	}
	background := s.GetColor(colorKey)

	hasIcon := iconDataUri != "" && iconDataUriRe.MatchString(iconDataUri)
	baseSize := 52
	if hasIcon {
		baseSize = 34
	}

	labelLen := len(s.Label)
	labelSize := baseSize
	if labelLen > 3 {
		calculated := int(math.Floor(float64(baseSize*3) / float64(labelLen)))
		if calculated < 16 {
			labelSize = 16
		} else {
			labelSize = calculated
		}
	}

	textColor := TextColorForBackground(background)
	font := fmt.Sprintf(`font-family="Arial, Helvetica, sans-serif" font-weight="bold" fill="%s" text-anchor="middle"`, textColor)

	var sb strings.Builder
	sb.WriteString(`<svg xmlns="http://www.w3.org/2000/svg" width="144" height="144" viewBox="0 0 144 144">`)
	sb.WriteString(fmt.Sprintf(`<rect width="144" height="144" rx="18" fill="%s"/>`, background))
	if hasIcon {
		sb.WriteString(fmt.Sprintf(`<image href="%s" x="46" y="8" width="52" height="52" preserveAspectRatio="xMidYMid meet"/>`, iconDataUri))
	}
	labelY := 82
	if hasIcon {
		labelY = 96
	}
	sb.WriteString(fmt.Sprintf(`<text x="72" y="%d" %s font-size="%d">%s</text>`, labelY, font, labelSize, EscapeXml(s.Label)))
	statusY := 120
	if hasIcon {
		statusY = 128
	}
	statusStr := StatusText[status]
	sb.WriteString(fmt.Sprintf(`<text x="72" y="%d" %s font-size="22">%s</text>`, statusY, font, statusStr))
	sb.WriteString(`</svg>`)

	return sb.String()
}

func SvgToImage(svg string) string {
	return "data:image/svg+xml;charset=utf8," + svg
}

type PendingCommand struct {
	RequestId string
	Control   string
	Command   string
	SentAt    time.Time
}

type UiStateSnapshot struct {
	ConnectionState string `json:"connectionState"`
	MapEnabled      *bool  `json:"mapEnabled"`
	IfrEnabled      *bool  `json:"ifrEnabled"`
	VfrEnabled      *bool  `json:"vfrEnabled"`
	LastRequestId   string `json:"lastRequestId,omitempty"`
	Revision        *int   `json:"revision,omitempty"`
}

type Model struct {
	MapEnabled      *bool
	IfrEnabled      *bool
	VfrEnabled      *bool
	ConnectionState string
	LastRequestId   string
	Revision        *int
	PendingCommand  *PendingCommand
	Errors          map[string]time.Time
}

func CreateModel() *Model {
	return &Model{
		ConnectionState: "offline",
		Errors:          make(map[string]time.Time),
	}
}

func (m *Model) ApplySnapshot(snapshot *UiStateSnapshot) {
	if snapshot == nil || !validConnectionStates[snapshot.ConnectionState] {
		m.MarkOffline()
		return
	}
	m.ConnectionState = snapshot.ConnectionState
	m.MapEnabled = snapshot.MapEnabled
	m.IfrEnabled = snapshot.IfrEnabled
	m.VfrEnabled = snapshot.VfrEnabled
	m.LastRequestId = snapshot.LastRequestId
	m.Revision = snapshot.Revision

	if m.PendingCommand != nil && m.LastRequestId != "" && m.LastRequestId == m.PendingCommand.RequestId {
		m.PendingCommand = nil
	}
}

func (m *Model) MarkOffline() {
	m.ConnectionState = "offline"
	m.MapEnabled = nil
	m.IfrEnabled = nil
	m.VfrEnabled = nil
	m.LastRequestId = ""
	m.Revision = nil
}

type BeginResult struct {
	Ok        bool   `json:"ok"`
	RequestId string `json:"requestId,omitempty"`
	Command   string `json:"command,omitempty"`
	Reason    string `json:"reason,omitempty"`
}

func (m *Model) BeginCommand(control string, now time.Time, idGen func() string) BeginResult {
	spec, exists := Controls[control]
	if !exists {
		return BeginResult{Ok: false, Reason: "unknown_control"}
	}
	if m.PendingCommand != nil {
		return BeginResult{Ok: false, Reason: "pending"}
	}
	if m.ConnectionState != "connected" {
		return BeginResult{Ok: false, Reason: m.ConnectionState}
	}
	requestId := "sd-" + idGen()
	m.PendingCommand = &PendingCommand{
		RequestId: requestId,
		Control:   control,
		Command:   spec.Command,
		SentAt:    now,
	}
	delete(m.Errors, control)
	return BeginResult{Ok: true, RequestId: requestId, Command: spec.Command}
}

func (m *Model) FailCommand(requestId string, now time.Time) bool {
	if m.PendingCommand == nil || m.PendingCommand.RequestId != requestId {
		return false
	}
	ctrl := m.PendingCommand.Control
	m.PendingCommand = nil
	m.Errors[ctrl] = now.Add(ErrorHoldDuration)
	return true
}

func (m *Model) ExpirePending(now time.Time) bool {
	if m.PendingCommand == nil || now.Sub(m.PendingCommand.SentAt) < ConfirmTimeout {
		return false
	}
	return m.FailCommand(m.PendingCommand.RequestId, now)
}

func (m *Model) KeyStatus(control string, now time.Time) string {
	if until, ok := m.Errors[control]; ok && until.After(now) {
		return "error"
	}
	if m.ConnectionState != "connected" {
		return m.ConnectionState
	}
	spec, exists := Controls[control]
	if !exists {
		return "stale"
	}
	var val *bool
	switch spec.StateKey {
	case "mapEnabled":
		val = m.MapEnabled
	case "ifrEnabled":
		val = m.IfrEnabled
	case "vfrEnabled":
		val = m.VfrEnabled
	}
	if val == nil {
		return "stale"
	}
	if *val {
		return "on"
	}
	return "off"
}
