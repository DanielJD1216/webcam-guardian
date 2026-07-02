# Webcam Guardian

A local-first webcam guardian with two tiers: a cheap local vision model (the **guard**) watches your webcam for free and labels what it sees; a frontier multimodal model of your choice (the **detective**) is called only when something needs judgment — it looks at the actual frame and decides, in plain English, whether you should be alerted.

**Bring your own detective:** any OpenAI-compatible vision endpoint works — OpenAI, Anthropic, Gemini, MiniMax, OpenRouter, or fully local and private via Ollama.

> 🚧 **Status: in development.** The complete engineering plan lives in [BUILD-PLAN.md](BUILD-PLAN.md). This README will be replaced with real quickstart docs, a provider table, a privacy section, and **measured** benchmarks as build milestones land (plan §11 / §15). No numbers will appear here that weren't measured on real hardware.

## How it will work

1. The guard (a small local detector, RT-DETR by default) analyzes webcam frames a few times per second and draws live boxes for person / car / dog.
2. When a relevant class appears — debounced, cooled down, and hard-capped — the actual frame is sent to your configured detective model.
3. The detective returns a structured decision (`alert`, `category`, `reason`, `message`). If it says alert, the message lands on your phone (Telegram) and inbox (email).
4. Everything is logged locally to JSONL. Nothing is mocked.

## License

MIT — see [LICENSE](LICENSE). One note: the optional `[yolo]` guard backend depends on Ultralytics (AGPL-3.0) and is strictly opt-in; the core install is MIT/Apache-clean.
