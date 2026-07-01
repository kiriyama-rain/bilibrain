# Changelog

## v2.0.0 (2026-06-24)

### Initial Open-Source Release

**Architecture:**
- Chrome Extension (MV3) + Flask backend + Web UI (SPA)
- Content extraction via content script injection
- AI chat via DeepSeek API with streaming (SSE)

**Features:**
- One-click page capture from Chrome extension popup
- Bilibili/YouTube subtitle extraction (WBI-signed API)
- Hard subtitle extraction via PaddleOCR (video frames)
- Audio transcription via faster-whisper
- AI-powered content discussion with structured system prompt
- Auto-save to local Markdown knowledge base
- SQLite persistence for capture and transcription history
- Real-time SSE progress for OCR transcription
- Flask start/stop control panel in Web UI

**Chrome Extension:**
- MV3 service worker with cookie-based B站 authentication
- WBI signature implementation (pure JS MD5)
- Content-type detection (webpage/video/audio)
- Cross-origin fetch proxy via background service worker

**Backend:**
- Flask Blueprint modular routing (tabs, capture, chat, save, transcribe)
- Pipeline architecture with pluggable processors (webpage, multimodal)
- Configurable AI backend (DeepSeek-compatible API)
- 600MB upload limit for video OCR processing
