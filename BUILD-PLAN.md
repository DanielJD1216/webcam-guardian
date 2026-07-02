# Webcam Guardian — End-to-End Build Plan

**For:** MiniMax M3 running inside opencode (the implementing agent)
**Prepared:** 2026-07-01 (rev 3 — owner inputs resolved: Mac dev machine, pay-as-you-go MiniMax key, Telegram + email alerts; and the project is now an **open-source, MIT-licensed repo with a bring-your-own-detective design** — see §2 and §15). Every API fact below was verified against live official docs on this date and independently re-verified by a second pass. Sources are cited inline. Where something could NOT be verified, it is explicitly marked `[VERIFY AT RUNTIME]` with a test that resolves it.

---

## 0. Read this first — three corrections to the original brief

The original brief was researched against live sources. Three claims in it are **wrong or unrealistic**, and this plan routes around them:

1. **`response_format` / structured-output JSON does NOT exist on the MiniMax chat-completions API.** Confirmed negative against the live OpenAPI spec for `POST /v1/chat/completions`: no `response_format`, no `json_schema`, no JSON mode for MiniMax-M3 (it exists only on the legacy `/v1/text/chatcompletion_v2` endpoint and only for the old MiniMax-Text-01 model). Function/tool calling IS supported. → **Structured JSON is obtained via a forced tool call** (function arguments are a JSON string shaped by your parameters schema), with a prompt-JSON + robust-parser fallback. See §7.

2. **LocateAnything-3B cannot run at 2–5 fps on a 16GB laptop GPU, and its weights are licensed NON-COMMERCIAL.** The only official latency number is ~2 s/image (A100, 4K, batch 4, hybrid mode). Comparable 0.2–3B VLM detectors (OWLv2 ~1.1 s/frame, Florence-2 ~1 s/frame on T4) confirm ~1 fps is the ceiling class, not 2–5 fps. It is also officially **Linux + NVIDIA only** (Windows hits a `NotImplementedError` in the attention fallback; no MPS). And the weights are under the NVIDIA License: *"academic and non-profit research purposes only. Commercial use is not permitted."* → **The dev machine is confirmed to be a Mac (§2), where the official LocateAnything path does not run at all** (and its pinned `decord==0.6.0` dependency has no Apple Silicon wheel — pip install fails outright). The guard is therefore **YOLO11n running locally on Apple's MPS backend** — still a free, always-on local neural net, so the two-tier story fully holds. LocateAnything survives only as an experimental appendix via community Metal ports (§5.3); attempt it only after everything else works, time-boxed, and never on the critical path.

3. **Thinking mode is ON by default on the OpenAI-compatible endpoint, and turning it off requires `extra_body`.** `thinking: {"type": "disabled"}` is the correct parameter (enum `disabled | adaptive`, default `adaptive` = ON). With the official OpenAI Python SDK it is a non-standard param and **must** be passed as `extra_body={"thinking": {"type": "disabled"}}` — passing it as a named kwarg raises `TypeError`, and omitting it means `<think>...</think>` tags pollute `content` and break JSON parsing. (Curiously, on MiniMax's Anthropic-compatible endpoint the default is the opposite: disabled.) See §7.

---

## 1. What we're building

A local-first webcam "guardian" with two tiers. A cheap, always-on local vision model (the **guard**) watches the webcam for free and labels what it sees (person / dog / car), drawing live boxes on a preview window. A frontier multimodal model (the **detective** — MiniMax M3 via API) is called only when a relevant class shows up and the cooldown allows it. The detective receives the **actual frame** (base64 JPEG), judges it with its own eyes, and returns a structured decision: alert or not, plus a plain-English message. Alerts go out through a swappable channel. Every event is logged locally. This must run live on real hardware for a screen recording — **no mocked outputs, no fake data.** The repo ships as a public, MIT-licensed open-source project: the guard runs locally, and the detective is **any OpenAI-compatible vision model** — MiniMax M3 is the maintainer's own setup, not a requirement (§15).

**Demo success looks like:** a live preview window with boxes, a visible "detective called" moment when a person appears, a real notification arriving with a sensible message ("Delivery driver dropping off a package — no action needed" vs. "Someone has been standing at your door for a while, not delivering anything"), and a continuous delivery event firing exactly one escalation thanks to the cooldown.

---

## 2. Owner inputs — RESOLVED (2026-07-01)

All blocking questions have been answered by the owner. These are decisions, not assumptions:

1. **Dev machine: a Mac.** Treat as Apple Silicon with unified memory (the brief's "16GB VRAM" = 16 GB unified). Consequences applied throughout: guard runs on `mps` (with automatic `cpu` fallback — YOLO11n clears 5 fps either way), camera backend is `CAP_AVFOUNDATION`, memory numbers for the README are process RSS (there is no VRAM), and the official LocateAnything path is **impossible here** (§5.3). Device-selection code (`mps` if available else `cpu`) also covers the unlikely Intel-Mac case, so nothing blocks on the exact model.
2. **MiniMax key: pay-as-you-go direct API key**, already connected in the opencode harness (build-environment Step 0 is done). The runtime app uses the same key from `.env` as `MINIMAX_API_KEY`. The M3 smoke test (§10) still runs first — it validates the image payload and `tool_choice`, not the key.
3. **Alert channels: Telegram AND email** — both fire on every alert (multi-channel fan-out, §8). Desktop/ntfy remain in the codebase as optional extras only.
4. **Licensing: personal project.** AGPL Ultralytics is fine; the non-commercial LocateAnything weights are fine for the experimental branch.
5. Webcam index 0; Python 3.11/3.12 in a plain `venv` (defaults stand). The one-time macOS camera permission (TCC) must be granted to the terminal/opencode host in milestone M0.
6. **Open source: yes.** Public repo, **MIT license**, bring-your-own-detective (any OpenAI-compatible endpoint; §15). Consequences: the default guard is **RT-DETR (Apache-2.0)** so the core stays MIT-clean; AGPL Ultralytics becomes an opt-in extra (still available as the owner's escape hatch); the local/private Ollama path is documented as first-class.

**One-time credentials the owner must produce during M5** (the implementing agent should prompt for these): a Telegram bot token from @BotFather + chat_id (discovery steps in §8), and a **Gmail App Password** (Google Account → Security → 2-Step Verification → App passwords — the normal account password will NOT work over SMTP).

---

## 3. Verified platform facts (the ground truth for all code)

### 3.1 MiniMax M3 API

| Fact | Value | Source |
|---|---|---|
| Model exists / GA | Yes — announced 2026-06-01, natively multimodal (text + image + video in, text out), 1M-token context | minimax.io/blog/minimax-m3 |
| Model string | **`MiniMax-M3`** (exact; enum-verified in the OpenAPI spec) | platform.minimax.io/docs/api-reference/api-overview |
| OpenAI-compatible endpoint | **`POST https://api.minimax.io/v1/chat/completions`** (base URL `https://api.minimax.io/v1`); China mainland uses `api.minimaxi.com` — note the extra "i"; international keys use `.io` | docs/api-reference/text-openai-api |
| Anthropic-compatible endpoint | `POST https://api.minimax.io/anthropic/v1/messages` (MiniMax's "Recommended" for coding tools / prompt caching). **This app uses the OpenAI-compatible one** — see §7 decision. | docs/guides/quickstart-preparation |
| Auth | `Authorization: Bearer $MINIMAX_API_KEY`. **No GroupId/GID** anywhere in current international docs — not needed. | chat-completions OpenAPI |
| Image attachment | OpenAI-style content part: `{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,<b64>","detail":"low"}}`. Also accepts https URLs. Optional `max_long_side_pixel` int field. Formats: JPEG/PNG/GIF/WEBP. Limits: ≤10 MB per image, ≤64 MB request body. No documented per-request image-count limit. | chat-completions OpenAPI (official "Image Understanding" example uses exactly this shape with MiniMax-M3) |
| Image token cost | `detail:"low"` ≈ up to ~600 tokens; `default` ~1k–5k; `high` up to ~15k+. Billed as normal input tokens; **meter via `response.usage`**, never assume a constant. | docs (verbatim table) |
| Thinking toggle | `"thinking": {"type": "disabled"}` (enum `disabled`/`adaptive`; **default `adaptive` = ON** on this endpoint). Via OpenAI SDK: `extra_body={"thinking": {"type": "disabled"}}`. When thinking is on and `reasoning_split` unset, thinking arrives inline in `content` as `<think>...</think>`. | chat-completions OpenAPI |
| Structured output | **NONE on this endpoint** (confirmed negative). Use tool calling: `tools=[{"type":"function","function":{name,description,parameters}}]`; response has `message.tool_calls[0].function.arguments` (JSON string), `finish_reason:"tool_calls"`. | chat-completions OpenAPI |
| Sampling params | `max_completion_tokens` (M3 max 524,288), `temperature` [0,2] default 1, `top_p` default 0.95. Ignored/unsupported: `presence_penalty`, `frequency_penalty`, `logit_bias`, `n>1`, audio input. | chat-completions OpenAPI |
| Pricing (pay-as-you-go, ≤512K input) | **$0.30/M input, $1.20/M output**, cache-read $0.06/M ("Permanent 50% off" badge). Doubles above 512K input. `service_tier:"priority"` = 1.5×. | docs/guides/pricing-paygo |
| Rate limits | **200 RPM / 10M TPM** for M3 (lower than M2.x's 500 RPM). Irrelevant at this app's call volume but explains any 429s. | docs/guides/rate-limits |
| Token Plan | Subscription keys (`sk-cp-...`, Plus $20/Max $50/Ultra $120 per month) are **not interchangeable** with paygo API keys; same endpoints; quota in 5-hour rolling + weekly windows. | docs/token-plan/intro |

### 3.2 NVIDIA LocateAnything-3B (reference — experimental branch only on this Mac)

> **Status for this build:** the dev machine is a Mac, so the official path below (Linux + NVIDIA) cannot run here at all. This table is kept as ground truth for the experimental Metal-port branch (§5.3) and for anyone running the repo on a Linux/NVIDIA box later.

| Fact | Value |
|---|---|
| Model ID | **`nvidia/LocateAnything-3B`** on Hugging Face (released 2026-05-26, Eagle family, ECCV 2026). Base: Qwen2.5-3B-Instruct + MoonViT-SO-400M encoder. |
| License | **NVIDIA License, NON-COMMERCIAL** (academic/non-profit research only). GitHub *code* is Apache-2.0; the *weights* are not. Fine for a personal research prototype; not shippable commercially. |
| Official support | **Linux + NVIDIA GPUs only** (Ampere/Hopper/Lovelace/Blackwell). Windows hits `NotImplementedError` on the eager-attention path (HF discussion #17). No MPS. TensorRT/vLLM/SGLang unsupported. |
| Load | `AutoModel.from_pretrained("nvidia/LocateAnything-3B", torch_dtype=torch.bfloat16, trust_remote_code=True)` + `AutoTokenizer`/`AutoProcessor` (both `trust_remote_code=True`). **Pin a revision** (`revision="c32291c..."` or current main SHA) — remote code changes under you otherwise. |
| Chat template | `processor.py_apply_chat_template(messages, tokenize=False, add_generation_prompt=True)` — note the nonstandard `py_` prefix — then `processor.process_vision_info(messages)`. |
| Detection prompt | `"Locate all the instances that matches the following description: person</c>car</c>dog."` (categories joined with `</c>`; the "that matches" grammar quirk is verbatim-correct). |
| Fast Mode | `generation_mode="fast"` on the **same checkpoint** (MTP-only parallel box decoding). `"hybrid"` (default) = MTP with autoregressive fallback — use hybrid; fast is "good for simple scenes" only. Recommended `max_new_tokens=8192`. |
| Output format | Text: `<ref>label</ref><box><x1><y1><x2><y2></box>` per object; integers normalized to **[0,1000]** (pixel = coord/1000 × dim). No object: `<box>none</box>`. **No confidence scores.** Parse: `r"<box><(\d+)><(\d+)><(\d+)><(\d+)></box>"`. |
| Pinned deps | `opencv-python-headless==4.11.0.86 transformers==4.57.1 numpy==1.25.0 Pillow==11.1.0 peft torchvision decord==0.6.0 lmdb==1.7.5` + torch per CUDA version. **These pins conflict with a modern env → isolate in its own venv (§5.3).** |
| Speed/memory (only official numbers) | A100, 4K image, batch 4, hybrid: ~8.03 s (la_flash backend, 11.7 GB peak) vs ~8.26 s (SDPA, **35.1 GB** peak). 12.7 boxes/sec on H100 batch 1. No consumer-GPU numbers exist → spike test required (§10 M2b). flash-attn (`la_flash`) is Linux-first; on Windows you're on SDPA = 3× memory. |
| Gotcha | `locateanything_worker.py` is **NOT in the HF model repo** (404) — it lives in GitHub at `NVlabs/Eagle/Embodied/locateanything_worker.py`; the HF model card also embeds the full worker class inline as copy-paste code. The HF repo ships `batch_infer.py` + `batch_utils/` + `kernel_utils/`. |

### 3.3 Glue layer

| Component | Verified choice |
|---|---|
| Desktop notifications | **`desktop-notifier` 6.2.0** (2025-08, maintained) with `DesktopNotifierSync`. Constructor: `DesktopNotifierSync(app_name="Webcam Guardian")`. macOS: requires a **signed** Python (python.org installer works; Homebrew silently fails); first send triggers the permission prompt. `plyer` is unmaintained (last release 2022) and its macOS backend uses an API deprecated since 2018 — do not use. |
| ntfy.sh | No auth on the public server; topic name = the password (use a long random string). Text: `requests.post(f"https://ntfy.sh/{topic}", data=body.encode(), headers={"Title":..., "Priority":"high", "Tags":"camera"})`. Image: `requests.put(url, data=jpeg_bytes, headers={"Filename":"alert.jpg","Title":...})`. **Limits: 250 messages/day, 2 MB per attachment, 60-request burst refilling 1/5s** — cooldown is mandatory. |
| Telegram | `https://api.telegram.org/bot<TOKEN>/sendPhoto`, multipart field name **`photo`**, `caption` ≤ **1024 chars** (sendMessage text ≤ 4096). chat_id: message the bot once, then read `getUpdates → result[0].message.chat.id`. Photo ≤10 MB, width+height ≤10000 px. |
| Webcam capture | `cv2.VideoCapture(index, backend)` with explicit backend: `CAP_DSHOW` (Windows, try `CAP_MSMF` if flaky), `CAP_AVFOUNDATION` (macOS), `CAP_V4L2` (Linux). `CAP_PROP_BUFFERSIZE` is only reliably honored on V4L2 → **use a daemon reader thread that keeps only the latest frame** (code in §6.1). |
| GUI rule | **`cv2.imshow`/`cv2.waitKey` must run on the MAIN thread** — on macOS a worker-thread window crashes with an NSWindow assertion; flaky elsewhere too. |
| Event log | **JSONL**, append-only, `write → flush() → os.fsync()` per event (crash-safe). SQLite is overkill for a single-process prototype. |

---

## 4. Environment & install matrix

One venv (`.venv`), Python 3.11/3.12, on the Mac:

```toml
# pyproject.toml — everything in core is MIT/Apache/BSD-compatible (keeps the repo MIT, §15)
[project]
dependencies = [
  "opencv-python>=4.10",     # NOT -headless: we need imshow for the preview
  "torch>=2.4",              # MPS support included on Apple Silicon
  "transformers>=4.48",      # default guard: RT-DETR (Apache-2.0)
  "openai>=1.60",            # client for ANY OpenAI-compatible detective endpoint
  "requests>=2.32",          # telegram channel (email uses stdlib smtplib)
  "python-dotenv>=1.0",
  "PyYAML>=6.0",
  "psutil>=5.9",             # memory (RSS) measurement for the README numbers
]
[project.optional-dependencies]
yolo = ["ultralytics>=8.3"]          # AGPL-3.0 — opt-in only, lazy-imported (§13 trap 14)
desktop = ["desktop-notifier>=6.2"]  # optional channel; needs signed python.org Python on macOS
```

- **Torch:** plain `pip install torch` — on Apple Silicon this includes MPS support out of the box. Device resolution: `mps` if `torch.backends.mps.is_available()` else `cpu`. Both guard options clear 5 analyzed fps on this hardware class.
- **Memory metric for the README:** there is no VRAM on a Mac — report process RSS (`psutil.Process().memory_info().rss`) and, when on MPS, `torch.mps.driver_allocated_memory()`.
- **Secrets:** `.env` (gitignored), loaded with python-dotenv — `MINIMAX_API_KEY`, `TELEGRAM_BOT_TOKEN`, `EMAIL_APP_PASSWORD`. Never in config.yaml, never printed (the screen will be recorded).
- **Step 0 — DONE.** The owner already has opencode connected to MiniMax M3 with a pay-as-you-go key. Two standing notes for the build sessions: keep `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` unset in that shell (stale values silently override the provider — documented by MiniMax), and if error 2013 "tool call result does not follow tool call" ever appears, **start a fresh opencode session** — the session history is poisoned once it happens.
- **Portability note:** if this repo ever runs on a Linux/Windows + NVIDIA machine, install the matching CUDA torch wheel, set `guard.device: cuda`, and measure VRAM via `nvidia-smi` — nothing else changes.

---

## 5. Architecture

### 5.1 Data flow

```
┌────────────┐   camera fps   ┌──────────────────┐
│ Capture     │ ─────────────▶ │ latest-frame slot │  (daemon thread, keep-newest only)
│ thread      │                └────────┬─────────┘
└────────────┘                          │ pulled at analyzed_fps
                                        ▼
                              ┌───────────────────┐
                              │ MAIN THREAD LOOP   │
                              │ guard.detect(frame)│──▶ draw boxes + HUD ──▶ cv2.imshow
                              └────────┬──────────┘
                                       │ trigger classes present?
                                       ▼
                              ┌───────────────────┐
                              │ Escalator          │  debounce (3 frames) + per-class
                              │ (pure logic)       │  cooldown (45s) + hard caps
                              └────────┬──────────┘
                                       │ enqueue (frame copy, labels, ts)
                                       ▼
                              ┌───────────────────┐        ┌──────────────┐
                              │ Detective worker   │──API──▶│ MiniMax M3    │
                              │ (ONE thread, queue)│◀──JSON─│ (image judge) │
                              └────────┬──────────┘        └──────────────┘
                                       │ alert==true
                                       ▼
                              ┌───────────────────┐
                              │ AlertChannel fan-out│  telegram + email (opt: desktop, ntfy)
                              └────────┬──────────┘
                                       ▼
                              events.jsonl  (every stage logs here)
```

**Threading contract (non-negotiable):**
- Capture runs in a daemon thread writing into a single lock-guarded "latest frame" slot.
- The main thread owns: guard inference, overlay drawing, `cv2.imshow`/`waitKey(1)`, and the escalation decision. (Guard inference on the main thread is fine — YOLO11n is ~10–60 ms; if the LocateAnything backend is active its subprocess call is async, see §5.3.)
- **Exactly one** detective worker thread consumes a `queue.Queue`. The API call (timeout 30 s, one retry on 429/5xx with 2 s backoff) and alert delivery both happen there, so the preview never freezes on network. A frozen preview ruins the screen recording; this is why.
- The queue carries a **copy** of the frame (`frame.copy()`), the guard labels, and the timestamp.

### 5.2 Guard backend interface

```python
# guardian/guard/base.py
from dataclasses import dataclass

@dataclass
class Detection:
    label: str                      # canonical: "person" | "car" | "dog"
    conf: float | None              # None for locateanything (emits no scores)
    box: tuple[float, float, float, float]   # x1, y1, x2, y2 in PIXELS

class GuardBackend:
    name: str
    def detect(self, frame_bgr) -> list[Detection]: ...
    def close(self): ...
```

Three implementations, selected by `guard.backend` in config:

1. **`rtdetr` (default — this drives the demo).** `PekingU/rtdetr_r18vd` via transformers. **Apache-2.0 — chosen as default so the repo can be MIT** (§15). 217 FPS on T4; runs on `mps` with `cpu` fallback (confirm in the M2 gate). COCO-trained: person=0, car=2, bus=5, truck=7, dog=16 — **map bus/truck → "car"** (a delivery van must trigger the car class; this is a deliberate decision).
2. **`yolo11n`** (optional extra — `pip install ".[yolo]"`): Ultralytics `YOLO("yolo11n.pt")`, `model.predict(frame, classes=[0,2,5,7,16], conf=cfg.conf_threshold, verbose=False, device=cfg.device)`. Fast even on CPU (~56 ms/img ONNX) but **AGPL-3.0** — lazy-imported inside this backend only, so the MIT core never touches it. This is the owner's escape hatch if RT-DETR misbehaves on MPS.
3. **`locateanything`** (the brief's hero — **experimental on this Mac**, §5.3): runs **out-of-process** behind the same interface.

Core of the default backend (verbatim pattern from the transformers RT-DETR docs):

```python
from transformers import RTDetrImageProcessor, RTDetrForObjectDetection
proc  = RTDetrImageProcessor.from_pretrained("PekingU/rtdetr_r18vd")
model = RTDetrForObjectDetection.from_pretrained("PekingU/rtdetr_r18vd").to(device).eval()

inputs = proc(images=pil_img, return_tensors="pt").to(device)
with torch.no_grad():
    outputs = model(**inputs)
res = proc.post_process_object_detection(
    outputs, target_sizes=torch.tensor([(pil_img.height, pil_img.width)]),
    threshold=cfg.conf_threshold)[0]
# model.config.id2label[label_id.item()] -> "person"/"car"/"bus"/"truck"/"dog";
# canonicalize via cfg.coco_ids mapping (bus/truck -> "car"), drop everything else.
```

### 5.3 LocateAnything on this Mac (experimental appendix — off the critical path)

**The official path is impossible here.** The model card supports Linux + NVIDIA only; the remote code's attention paths are CUDA-oriented (no MPS, and even Windows crashes with `NotImplementedError`); and the pinned `decord==0.6.0` has no Apple Silicon wheel, so the required deps don't even pip-install. Do not sink build time into trying.

**Two community ports exist (unofficial, NVIDIA-unsupported, both surfaced and verified to exist during research):**

1. **`github.com/mudler/locate-anything.cpp`** — a C++17 ggml port; build with `-DLA_GGML_METAL=ON` for Apple GPU support. Implements all three generation modes (fast/slow/hybrid); greedy decoding only, single image per call; claims byte-identical detections vs PyTorch at q8_0. This is the more promising route.
2. **`yuuko-eth/LocateAnything-3B-GGUF`** (Q4_K_M 2.1 GB recommended, plus `mmproj-LocateAnything-3B-BF16.gguf` 0.87 GB) — requires building the llama.cpp **fork branch `mtmd-grounders`** (stock llama.cpp will NOT load these GGUFs); `llama-server` needs the `--special` flag or the coordinate tokens don't emit.

**If pursued (milestone M2b, time-boxed):** wrap the port's CLI behind the same `GuardBackend` interface as a subprocess — spawn once, one exchange per frame: send the detection prompt (`"Locate all the instances that matches the following description: person</c>car</c>dog."`) with a JPEG resized to long side ≤960 px, parse `<ref>label</ref><box><x1><y1><x2><y2></box>` with coords normalized to [0,1000] (all formats in §3.2). Because it will be ~1 s/frame class at best, the client must be **asynchronous**: fire the request, keep drawing the *previous* boxes, swap when the reply lands; the HUD shows the true analyzed fps. Expect no confidence scores (`Detection.conf=None`).

**Decision rule:** build M0–M7 with YOLO11n first. Only then, optionally, attempt the Metal port with a hard 1–2 hour time-box. If it works at ≥0.5 fps, it becomes a selectable `guard.backend` for the recording; if not, note the attempt in the README and ship with YOLO11n. The two-tier narrative (free local guard + paid frontier detective) does not depend on which local model plays the guard.

### 5.4 Escalation logic (pinned semantics — implement exactly this)

- **Debounce:** a trigger class must be present in **≥ `debounce_frames` (3) consecutive analyzed frames** before it is escalation-eligible. Kills one-frame flickers.
- **Cooldown gates detective CALLS, not alerts.** Per trigger class, `now - last_call_dispatched_at >= cooldown_seconds` (45 s default). The timer starts **when the call is dispatched, regardless of the verdict** — an `alert:false` response still consumes the cooldown. (Otherwise a lingering person = a paid API call every few seconds forever.)
- **Hard caps:** `max_detective_calls_per_run` (30) and `max_alerts_per_hour` (10). When a cap trips: log `{"type":"cap_hit", ...}` and skip silently. These counters double as the README's required call-count numbers.
- Multiple trigger classes in one frame (person + car) = **one** call carrying both labels; the cooldown is charged to both classes.

---

## 6. Repo layout & config

```
webcam-guardian/
├── README.md                    # for strangers: quickstart, provider table, privacy, results (§15)
├── LICENSE                      # MIT
├── pyproject.toml               # core deps MIT/Apache-clean; extras: [yolo] [desktop]
├── config.example.yaml          # committed template; real config.yaml is gitignored
├── .env.example                 # MINIMAX_API_KEY=  TELEGRAM_BOT_TOKEN=  EMAIL_APP_PASSWORD=
├── .gitignore                   # .env, config.yaml, events.jsonl, snapshots/, .venv*, *.pt — from the FIRST commit
├── guardian/
│   ├── __init__.py
│   ├── main.py                  # entry point: python -m guardian.main
│   ├── config.py                # YAML + env loader, typed access, validation
│   ├── capture.py               # LatestFrameCamera (§6.1)
│   ├── guard/
│   │   ├── base.py              # Detection, GuardBackend
│   │   ├── yolo.py              # default
│   │   ├── rtdetr.py            # Apache-2.0 alternative
│   │   └── la_client.py         # experimental Mac-port subprocess client (§5.3)
│   ├── escalate.py              # Escalator: debounce + cooldown + caps
│   ├── detective.py             # provider-agnostic OpenAI-compatible client (§7)
│   ├── prompts/judge.txt        # user-editable judgment prompt (house rules live here)
│   ├── alerts/
│   │   ├── base.py              # AlertChannel.send(title, body, image_path|None) + fan-out dispatcher
│   │   ├── telegram.py          # primary
│   │   ├── email_channel.py     # primary (stdlib smtplib; named to avoid shadowing stdlib `email`)
│   │   ├── desktop.py           # optional (desktop-notifier; needs signed Python on macOS)
│   │   └── ntfy.py              # optional
│   ├── overlay.py               # boxes, labels, HUD (fps, call count, cooldown state)
│   └── storage.py               # EventLog (JSONL, fsync per event), snapshot saver
├── scripts/
│   ├── smoke_camera.py          # M0: open cam, print frame shape, save one JPEG
│   ├── smoke_detective.py       # M3: one real frame → M3 → print decision + usage + latency
│   ├── spike_la.py              # M2b: 20-frame LocateAnything timing on target hardware
│   ├── dry_test_judgment.py     # M6: batch of saved frames → decision table (§11)
│   └── measure.py               # M7: 60s guard bench + 10-call latency bench → README numbers
└── tests/
    ├── test_escalate.py         # pure-logic: debounce, cooldown, caps (no hardware needed)
    └── test_parsing.py          # detective JSON parsing incl. <think> stripping, malformed JSON
```

### 6.1 Capture (verbatim-usable)

```python
# guardian/capture.py
import sys, threading, cv2

def default_backend():
    if sys.platform == "win32":  return cv2.CAP_DSHOW        # try CAP_MSMF if DSHOW misbehaves
    if sys.platform == "darwin": return cv2.CAP_AVFOUNDATION
    return cv2.CAP_V4L2

class LatestFrameCamera:
    """Reader thread consumes at camera rate; callers always get the newest frame."""
    def __init__(self, index=0, backend=None, width=1280, height=720):
        self.cap = cv2.VideoCapture(index, backend or default_backend())
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open camera {index} — check OS camera permission")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # best-effort (V4L2 honors, others may not)
        self._lock = threading.Lock()
        self._frame = None
        self._stopped = False
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while not self._stopped:
            ok, frame = self.cap.read()
            if ok:
                with self._lock:
                    self._frame = frame

    def read(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def release(self):
        self._stopped = True
        self.cap.release()
```

### 6.2 config.yaml (exact schema, with defaults)

```yaml
camera:
  index: 0
  backend: auto            # auto | dshow | msmf | avfoundation | v4l2
  width: 1280
  height: 720

guard:
  backend: rtdetr          # rtdetr (default, Apache-2.0) | yolo11n (extra, AGPL) | locateanything (experimental, §5.3)
  device: auto             # auto → mps on Apple Silicon, cuda on NVIDIA, else cpu
  analyzed_fps: 5          # target analysis rate (actual rate shown in HUD & logged)
  conf_threshold: 0.4
  draw_classes: [person, dog, car]
  trigger_classes: [person, car]
  coco_ids: {person: [0], car: [2, 5, 7], dog: [16]}   # bus/truck count as "car" (delivery vans!)
  la_command: []           # experimental Mac-port launch command (§5.3); empty = backend unavailable
  la_input_long_side: 960

escalation:
  debounce_frames: 3
  cooldown_seconds: 45
  max_detective_calls_per_run: 30
  max_alerts_per_hour: 10

detective:                 # ANY OpenAI-compatible endpoint — this block IS the bring-your-own-model surface (§15)
  base_url: https://api.minimax.io/v1   # e.g. api.openai.com/v1 · http://localhost:11434/v1 (Ollama) · openrouter.ai/api/v1
  model: MiniMax-M3
  api_key_env: MINIMAX_API_KEY          # name of the env var holding the key; "" for keyless local servers
  extra_body: {thinking: {type: disabled}}   # provider-specific params, merged verbatim into the request
  timeout_seconds: 30
  max_completion_tokens: 500
  temperature: 0.2         # low for consistent judgments
  image_long_side: 1024
  jpeg_quality: 80
  image_detail: low        # low | default | high (OpenAI/MiniMax semantics; ignored harmlessly elsewhere; low ≈ ≤600 tokens on MiniMax)
  use_tool_call: true      # forced tool call for strict JSON; set false for models with weak tool calling
  scene_description: "a front door / home entry area"

alert:
  channels: [telegram, email]   # all listed channels fire on every alert; options: telegram | email | desktop | ntfy
  attach_snapshot: true         # telegram/email/ntfy attach the judged frame
  telegram_chat_id: ""          # one-time discovery steps in §8
  email:
    smtp_host: smtp.gmail.com
    smtp_port: 465              # SSL
    from_addr: ""               # the Gmail account sending (may equal to_addr)
    to_addr: ""                 # where alerts land
  ntfy_topic: ""                # optional channel only; long random string (topic IS the password)

log:
  events_path: events.jsonl
  snapshots_dir: snapshots
  save_escalation_frames: true
```

---

## 7. The Detective: provider-agnostic client (MiniMax M3 as the verified reference)

**Provider-agnostic by design (§15):** `detective.py` contains no MiniMax-specific code — `base_url`, `model`, `api_key_env`, and `extra_body` all come from config, and the dual JSON strategy below (tool call → hardened prompt-JSON parser) is exactly what keeps arbitrary models working, including small local ones that flub tool calls. MiniMax M3 is simply the maintainer's verified reference configuration.

**Endpoint decision:** the **OpenAI-compatible** endpoint (`https://api.minimax.io/v1`), because (a) the official image-understanding example uses exactly this shape with base64 data URLs, (b) the OpenAI SDK is the simplest client, (c) the Anthropic-compatible endpoint's base64 image support is unverified (only `{"type":"url"}` appears in its official examples). Do not flip-flop between endpoints — their thinking defaults are opposites.

**JSON strategy:** forced tool call primary; prompt-JSON + hardened parser fallback. `tool_choice` forcing is standard OpenAI shape but was not explicitly verifiable in MiniMax's docs → `[VERIFY AT RUNTIME]` in `smoke_detective.py`; if the API rejects `tool_choice`, drop it and keep `tools` (the system prompt already instructs the tool call), and if tool calling proves unreliable set `use_tool_call: false`.

```python
# guardian/detective.py  (core — this is the make-or-break integration; copy carefully)
import base64, json, os, re, time
import cv2
from openai import OpenAI

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

ASSESSMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "report_assessment",
        "description": "Report the security assessment of this webcam frame.",
        "parameters": {
            "type": "object",
            "properties": {
                "alert":    {"type": "boolean", "description": "True only if the resident should be notified right now."},
                "category": {"type": "string", "description": "One of: delivery, visitor, resident, pet, vehicle, suspicious_person, prowler, package_theft, false_positive, other."},
                "reason":   {"type": "string", "description": "One sentence describing what is actually visible in the frame."},
                "message":  {"type": "string", "description": "The short, calm, specific notification text the resident reads. Empty string if alert is false."},
            },
            "required": ["alert", "category", "reason", "message"],
        },
    },
}

SYSTEM_PROMPT = """You are a home-security camera judge. You receive ONE still frame from a webcam \
pointed at {scene}, plus the local time and the label(s) a cheap local detector flagged. Decide whether \
the resident should be alerted right now.

Guidelines:
- A delivery driver actively delivering (uniform, package, delivery van, walking to/from the door): \
usually NO alert; category "delivery".
- Routine events (a resident-like person walking straight in, a pet, a car simply passing on the street): NO alert.
- An unknown person lingering, peering into windows, trying the door handle, circling back repeatedly, \
or concealing their face: ALERT; category "suspicious_person" or "prowler".
- Someone taking a package AWAY from the door: ALERT; category "package_theft".
- A vehicle stopped directly outside for a long time at odd hours: alert only if genuinely unusual.
- Empty scene, shadow, reflection, or obvious detector mistake: NO alert; category "false_positive".
- When genuinely uncertain, prefer NO alert, and say why in "reason".

Report your decision by calling the report_assessment tool. "message" must read like a notification a \
person would actually want to receive — specific and plain, e.g. "Delivery driver is dropping off a \
package at your door." or "Someone in a dark hoodie has been standing at your door for a while and \
isn't delivering anything.""""

def encode_frame(frame_bgr, long_side=1024, quality=80) -> str:
    h, w = frame_bgr.shape[:2]
    scale = long_side / max(h, w)
    if scale < 1.0:
        frame_bgr = cv2.resize(frame_bgr, (round(w * scale), round(h * scale)))
    ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return base64.b64encode(buf).decode("ascii")

class Detective:
    def __init__(self, cfg):
        self.cfg = cfg
        api_key = os.environ.get(cfg.api_key_env, "") if cfg.api_key_env else ""
        self.client = OpenAI(api_key=api_key or "none",      # "none": keyless local servers (Ollama)
                             base_url=cfg.base_url,
                             timeout=cfg.timeout_seconds, max_retries=1)

    def judge(self, frame_bgr, guard_labels: list[str]) -> dict:
        b64 = encode_frame(frame_bgr, self.cfg.image_long_side, self.cfg.jpeg_quality)
        user_content = [
            {"type": "text", "text": (f"Camera frame from {self.cfg.scene_description}. "
                                      f"Local time: {time.strftime('%A %H:%M')}. "
                                      f"Local detector flagged: {', '.join(guard_labels)}.")},
            {"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{b64}", "detail": self.cfg.image_detail}},
        ]
        kwargs = dict(
            model=self.cfg.model,                             # "MiniMax-M3"
            messages=[{"role": "system",
                       "content": SYSTEM_PROMPT.format(scene=self.cfg.scene_description)},
                      {"role": "user", "content": user_content}],
            max_completion_tokens=self.cfg.max_completion_tokens,
            temperature=self.cfg.temperature,
            extra_body=self.cfg.extra_body or None,   # MiniMax: {"thinking":{"type":"disabled"}} — must ride extra_body
        )
        if self.cfg.use_tool_call:
            kwargs["tools"] = [ASSESSMENT_TOOL]
            kwargs["tool_choice"] = {"type": "function",
                                     "function": {"name": "report_assessment"}}  # [VERIFY AT RUNTIME]
        t0 = time.monotonic()
        resp = self.client.chat.completions.create(**kwargs)
        latency = round(time.monotonic() - t0, 2)

        msg, decision, parse_error = resp.choices[0].message, None, None
        try:
            if getattr(msg, "tool_calls", None):
                decision = json.loads(msg.tool_calls[0].function.arguments)
            else:                                             # prompt-JSON / fallback path
                text = THINK_RE.sub("", msg.content or "").strip()   # strip <think> defensively
                m = re.search(r"\{.*\}", text, re.DOTALL)
                decision = json.loads(m.group(0)) if m else None
        except (json.JSONDecodeError, AttributeError, IndexError) as e:
            parse_error = repr(e)

        if not isinstance(decision, dict) or "alert" not in decision:
            decision = {"alert": False, "category": "parse_error",
                        "reason": f"unparseable model output: {parse_error}",
                        "message": ""}                        # safe default: log, don't alert

        u = resp.usage
        return {"decision": decision, "latency_s": latency,
                "prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens,
                "raw_finish_reason": resp.choices[0].finish_reason}
```

Every `judge()` result — including parse failures and the token usage — is written to `events.jsonl`. The usage fields summed across a session are the README's cost numbers.

The `SYSTEM_PROMPT` shown inline is the default content; at M8 it moves to `guardian/prompts/judge.txt` and is loaded at startup so end users can edit house rules without touching code (§15).

---

## 8. Alerts

```python
# guardian/alerts/base.py
class AlertChannel:
    name: str
    def send(self, title: str, body: str, image_path: str | None = None) -> None: ...

def dispatch(channels: list[AlertChannel], title, body, image_path, log):
    for ch in channels:                     # every configured channel fires, independently
        try:
            ch.send(title, body, image_path)
            log.log({"type": "alert_sent", "channel": ch.name, "title": title})
        except Exception as e:              # a dead channel must never crash the loop
            log.log({"type": "alert_error", "channel": ch.name, "error": repr(e)})
```

**Telegram (primary).** One-time setup: create a bot with @BotFather (`/newbot` → token into `.env` as `TELEGRAM_BOT_TOKEN`), send the bot any message from your account, then `GET https://api.telegram.org/bot<TOKEN>/getUpdates` → `result[0].message.chat.id` → `config.yaml`.

```python
# guardian/alerts/telegram.py (core)
API = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}"
if image_path:
    with open(image_path, "rb") as f:      # multipart field name MUST be 'photo'
        requests.post(f"{API}/sendPhoto",
                      data={"chat_id": chat_id, "caption": f"{title}\n{body}"[:1000]},
                      files={"photo": f}, timeout=30)
else:
    requests.post(f"{API}/sendMessage",
                  data={"chat_id": chat_id, "text": f"{title}\n{body}"[:4000]}, timeout=10)
```

**Email (primary).** Stdlib only — no new dependency. Gmail requires an **App Password** (Google Account → Security → 2-Step Verification → App passwords); the normal account password is rejected over SMTP, and there is no "less secure apps" toggle anymore. SMTP takes 1–3 s per send — fine, it runs on the detective worker thread.

```python
# guardian/alerts/email_channel.py (core)  — module name avoids shadowing stdlib `email`
import os, smtplib
from email.message import EmailMessage

msg = EmailMessage()
msg["Subject"] = title
msg["From"], msg["To"] = cfg.from_addr, cfg.to_addr
msg.set_content(body)
if image_path:
    with open(image_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="image", subtype="jpeg", filename="alert.jpg")
with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30) as s:
    s.login(cfg.from_addr, os.environ["EMAIL_APP_PASSWORD"])
    s.send_message(msg)
```

**Optional extras** (implemented behind the same interface, off by default): **desktop** — `DesktopNotifierSync(app_name="Webcam Guardian").send(title, body)`; on macOS only works from a signed Python (python.org installer, not Homebrew). **ntfy** — POST text with `Title`/`Priority: high`/`Tags: camera` headers, PUT JPEG bytes with `Filename: alert.jpg` for the snapshot; public-server caps: 250 msgs/day, 2 MB/attachment.

---

## 9. Main loop, overlay & HUD (demo legibility)

`main.py` sketch (main thread only):

```
load config + .env → EventLog → camera → guard backend → Escalator → Detective worker thread → channel
last_analysis = 0
while True:
    frame = camera.read();  if frame is None: continue
    if now - last_analysis >= 1/analyzed_fps:
        detections = guard.detect(frame)          # (async swap for locateanything backend)
        present = {d.label for d in detections if d.label in trigger_classes}
        to_escalate = escalator.observe(present, now)
        if to_escalate: queue.put((frame.copy(), sorted(to_escalate), now)); log escalation_dispatched
        last_analysis = now
    overlay.draw(frame, detections, hud)          # boxes + labels (+conf when available)
    cv2.imshow("Webcam Guardian", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'): break
```

HUD (top-left, small monospace, dark backing strip — this is what makes the recording legible):
`guard: yolo11n 4.8fps | detective calls: 3 (run) | person cooldown: 32s | last: DELIVERY no-alert "Driver dropping off package" 3.1s`
Plus a bright banner for 2 s when a call dispatches (`▶ DETECTIVE CALLED: person`) and when an alert fires (`🔔 ALERT SENT`).

Event log — one JSONL line per event, types: `startup`, `guard_stats` (periodic), `escalation_dispatched`, `detective_result` (full decision + usage + latency), `alert_sent`, `alert_error`, `cap_hit`, `parse_error`, `shutdown`.

---

## 10. Build order (milestones with gates — do them in this order)

| # | Milestone | Gate to pass before moving on |
|---|---|---|
| **M0** | Env + permissions: venv, requirements, `.env`; `scripts/smoke_camera.py` opens the cam, prints frame shape, saves `snapshots/smoke.jpg`. | A real JPEG from the real webcam exists. (Camera permission prompt handled here, not during the demo.) |
| **M1** | Capture + preview: `LatestFrameCamera` + main-thread imshow + fps HUD. | Live window at camera fps, `q` quits cleanly. |
| **M2** | Guard default: RT-DETR (`PekingU/rtdetr_r18vd`, Apache-2.0) on `mps` + overlay boxes + `guard_stats` logging. If RT-DETR misbehaves on MPS: `pip install ".[yolo]"`, set `guard.backend: yolo11n`, note it in the README. | Person/dog/car boxes track live at ≥ `analyzed_fps`; RSS measured and logged. |
| **M2b** | *(optional, time-boxed 1–2 h, only AFTER M7 passes)* LocateAnything-on-Mac experiment: build `mudler/locate-anything.cpp` with `-DLA_GGML_METAL=ON` (fallback: `mtmd-grounders` llama.cpp fork + Q4_K_M GGUF), time 20 real frames at 960 px via `scripts/spike_la.py`. | **Decision gate:** ≥0.5 fps sustained → wire it as the selectable `locateanything` subprocess backend for the recording. Else: the default guard drives the recording and the README documents the attempt. Never let this block M3–M8. |
| **M3** | Detective smoke test — **before any pipeline integration**: `scripts/smoke_detective.py` sends one saved frame to M3. Verifies in one run: the key works (paygo vs `sk-cp-` question, §2 Q2), the base64 `image_url` shape, `tool_choice` acceptance, thinking disabled (assert no `<think>` in content), latency, and usage numbers. | Printed decision dict + latency + tokens from a real call. If `tool_choice` is rejected → set the documented fallback and re-run. |
| **M4** | Escalation + integration: `Escalator` (with `tests/test_escalate.py` — pure logic, test debounce/cooldown/caps thoroughly), detective worker thread, full event logging. | Walking into frame produces exactly ONE call; standing there for 2 min produces ≤3 calls (45 s cooldown); `alert:false` results also consume cooldown. |
| **M5** | Alert channels: Telegram + email fan-out. One-time credential setup with the owner: BotFather token + chat_id discovery; Gmail App Password. | A real Telegram message (with photo) AND a real email both land, carrying the model's `message`. A failure in one channel doesn't stop the other. |
| **M6** | Judgment dry test: capture/collect 15–20 real frames covering {person plain, delivery-with-package, empty, pet, car/van}; `scripts/dry_test_judgment.py` runs each through `Detective.judge` and prints a table (file, guard label, alert, category, message, latency, tokens). | Table reviewed; delivery-vs-stranger calls are sensible. This is the make-or-break filmability check. |
| **M7** | Bench + README: `scripts/measure.py` (60 s guard bench: analyzed fps, p50/p95 inference ms, memory; 10 sequential detective calls: p50/p95 latency; 5-min integrated run: calls, alerts, cooldown skips) → paste outputs into README template. | README contains only **measured** numbers. No invented figures — the brief forbids mocks, and that includes fake benchmarks. |
| **M8** | Open-source packaging (§15): MIT LICENSE, README for strangers (quickstart, provider table, privacy section, model-validation harness), `config.example.yaml`, `.env.example`, gitignore audit, and an end-to-end test of at least one non-MiniMax provider row (Ollama is free and also proves the keyless path). | A stranger can clone → point config at any OpenAI-compatible vision model → run, without reading the code. Nothing personal (keys, frames, logs) anywhere in git history. |

---

## 11. Dry-test checklist mapping & README template

Brief requirement → where it's satisfied:

1. **M3 vision reliability (make-or-break)** → M6 table, 15–20 real frames.
2. **Latency** → M3 smoke + M7 bench (p50/p95 of escalation→decision).
3. **Guard on 16GB** → M2 (+M2b) VRAM/RSS measurements at the working frame rate.
4. **Cooldown** → M4 gate: one continuous delivery event ⇒ one alert.
5. **Judgment quality** → M6: count FP/FN on the delivery-vs-stranger distinction, record in README.
6. **Cost sanity** → every `detective_result` logs usage; M7 sums them; §12 formula converts to $/day.

README must include: how to run (3 commands), config reference, the alert-channel setup notes, and a **Results** section:

```markdown
## Dry-test results (measured YYYY-MM-DD on <hardware>)
- Guard: <backend> @ <analyzed fps> fps, inference p50 <ms> / p95 <ms>, memory <GB>
- Detective latency: p50 <s> / p95 <s> over <n> calls
- Judgment table: <n> frames, <fp> false positives, <fn> false negatives (delivery-vs-stranger)
- Session: <calls> detective calls, <alerts> alerts, <skips> cooldown skips in <minutes> min
- Tokens: <in> in / <out> out total → est. $<x>/day at observed escalation rate
```

## 12. Cost & rate-limit budget

Per detective call at `detail:"low"` + 1024 px frame: image ≤~600 tokens + ~350 prompt tokens in, ~120 out → **≈ $0.0004/call** ($0.30/M in, $1.20/M out). At the capped worst case (30 calls/run, a few runs/day): **well under $0.10/day**. Even 1,000 calls ≈ $0.43. Rate limits (200 RPM) are three orders of magnitude away from this app's single-worker cadence. The real budget constraint is **ntfy.sh's 250 messages/day** if that channel is chosen — the alert caps handle it.

---

## 13. Trap list for the implementing agent (each one is a verified failure mode)

1. `thinking` and `reasoning_split` are non-standard params → **`extra_body`** with the OpenAI SDK. Omitting `thinking` = thinking ON = `<think>` tags in content. Strip `<think>` in the parser anyway (defense in depth).
2. **No `response_format` on `/v1/chat/completions`.** Don't reach for it; it will 4xx or be ignored. Tool call or prompt-JSON only.
3. `cv2.imshow`/`waitKey` **main thread only** (hard crash on macOS otherwise). Detective calls **never** on the main thread.
4. Do not attempt LocateAnything's official PyTorch stack on this Mac — it is Linux+NVIDIA-only and its pinned `decord==0.6.0` has no Apple Silicon wheel (pip install fails). The only Mac routes are the unofficial ggml/Metal ports (§5.3), strictly off the critical path.
5. Cooldown gates **calls**, starts at **dispatch**, regardless of verdict. Alert-only cooldown burns money on lingering false positives.
6. Frame to detective: resize long side ≤1024, JPEG q80, `detail:"low"`. Raw 4K frames at default detail = 5–8× the tokens and slower calls.
7. macOS camera permission (TCC) attributes to the terminal/opencode host app; denial = `read()` silently returning no frames, not an error. Trigger and grant it in M0, not on recording day. (The optional desktop channel additionally needs a signed python.org Python — Homebrew Python notifications silently fail.)
8. Use `cv2.CAP_AVFOUNDATION` explicitly on macOS. Gmail SMTP needs an **App Password** (2FA account) in `EMAIL_APP_PASSWORD` — the normal account password is rejected. And name the email module `email_channel.py`, never `email.py` (stdlib shadowing).
9. Secrets only in `.env` (gitignored). The screen will be recorded — never print the key, and don't echo `.env` in the demo terminal.
10. `tool_choice` forcing is `[VERIFY AT RUNTIME]` (M3 smoke test). Rejection path is coded, not improvised.
11. LocateAnything: worker class comes from the **HF model card text / GitHub Eagle repo**, not the HF weights repo; pin `revision=`; output has **no confidence scores** (the `Detection.conf=None` path must not crash overlay/logging).
12. opencode error 2013 mid-build → fresh session, don't retry into poisoned history.
13. Parse failure from the detective = `alert:false` + logged raw output. Never crash, never alert on garbage.
14. License hygiene: `ultralytics` (AGPL) must never be imported in the core path — lazy-import it inside the `yolo11n` backend only, and keep it an optional extra so the repo stays MIT. Likewise the non-commercial LocateAnything weights are documentation-only, never a default.
15. Public-repo git hygiene: `.env`, `config.yaml`, `events.jsonl`, `snapshots/` gitignored **from the first commit** — a leaked key or a webcam frame in git history survives later deletion. `config.example.yaml` and `.env.example` are what get committed.

---

## 14. Out of scope (unchanged from brief)

Multi-camera, cloud deployment, recording/DVR, mobile app, motion-gated detection (Frigate-style tier-0 motion gating is noted as the "real product" architecture, but fixed-interval sampling at `analyzed_fps` is simpler and sufficient for this prototype).

---

## 15. Open-source packaging (v0.1)

The repo ships public under **MIT**: *"cheap local guard + bring-your-own frontier detective."* MiniMax M3 is the maintainer's setup, not a dependency.

**Bring-your-own-detective contract.** v0.1 supports exactly one protocol: **OpenAI-compatible chat completions with `image_url` vision input**. No per-provider SDK adapters. That single contract covers OpenAI, Anthropic (via its OpenAI-SDK compatibility layer), Google Gemini (via its OpenAI-compat endpoint), MiniMax, OpenRouter, Groq, and local servers (Ollama, LM Studio, vLLM). The README carries a provider table of copy-paste config blocks:

| Provider | base_url | api_key_env | extra_body | Status |
|---|---|---|---|---|
| MiniMax | `https://api.minimax.io/v1` | `MINIMAX_API_KEY` | `{thinking: {type: disabled}}` | ✅ verified 2026-07-01 (§3.1) |
| OpenAI | `https://api.openai.com/v1` | `OPENAI_API_KEY` | — | standard; confirm current vision-model id |
| Anthropic | OpenAI-SDK compat layer — confirm base URL at docs.anthropic.com | `ANTHROPIC_API_KEY` | — | `[CONFIRM against provider docs at M8]` |
| Google Gemini | OpenAI-compat endpoint — confirm at ai.google.dev | `GEMINI_API_KEY` | — | `[CONFIRM against provider docs at M8]` |
| OpenRouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | — | standard |
| **Ollama (local, private)** | `http://localhost:11434/v1` | *(keyless)* | — | standard; **the privacy-first path** |

Only the MiniMax row was verified in this research pass. At milestone M8 the implementing agent must sanity-check the other rows against current provider docs (model names churn) and run at least one non-MiniMax row end-to-end — Ollama is free and also exercises the keyless code path.

**The local/private path is first-class.** README gets its own section: point `base_url` at Ollama with a local vision model → zero frames leave the machine, zero API cost. Small local VLMs judge worse than frontier models — which is exactly what the model-validation harness is for: `scripts/dry_test_judgment.py` doubles as the public **"test your model"** tool (drop 15–20 of your own frames in a folder, run it, read the decision table). This turns the owner's M6 QA step into the repo's answer to "which models work?"

**Privacy disclosure (required README section, written bluntly):** with a cloud detective, every escalated frame — a photo of whoever is at your door — is sent to that provider under its data terms. The debounce/cooldown/caps bound how often. The Ollama path avoids it entirely. This is a security tool; say it plainly.

**User-editable judgment prompt:** the system prompt lives in `guardian/prompts/judge.txt` (loaded by `detective.py`), so users add house rules — "we have a golden retriever," "deliveries go to the side door" — without touching code.

**README structure for strangers:** what it is (2 paragraphs + the §5.1 diagram) → quickstart (3 commands + `config.example.yaml`) → provider table → privacy section → alert-channel setup (Telegram/email primary; desktop/ntfy optional) → config reference → measured results (§11) → model-validation harness → LocateAnything experimental appendix (§5.3, with its non-commercial license called out) → license notes (MIT core; `[yolo]` extra is AGPL and opt-in).

---

## 16. Source index (all fetched & cross-verified 2026-07-01)

- MiniMax: `platform.minimax.io/docs/api-reference/text-chat-openai` (chat completions OpenAPI — image_url shape, thinking enum, tools, params), `.../text-openai-api` (quickstart, extra_body), `.../api-overview` (model strings), `.../guides/pricing-paygo`, `.../guides/rate-limits`, `.../token-plan/intro`, `.../token-plan/other-tools` (opencode setup), `minimax.io/blog/minimax-m3`, `huggingface.co/MiniMaxAI/MiniMax-M3` (~428B params / ~23B active, BF16 ≈ 854 GB — the brief's "cannot self-host" premise confirmed). Note: the docs site intermittently 502/504s; the values above were verified via raw doc fetches the same day.
- LocateAnything: `huggingface.co/nvidia/LocateAnything-3B` (model card + LICENSE), `github.com/NVlabs/Eagle` (Embodied README, `locateanything_worker.py`, issues #68/#69/#71/#76), `research.nvidia.com/labs/lpr/locate-anything/`, HF discussions #17/#18 (attention/Windows), unofficial ports: `yuuko-eth/LocateAnything-3B-GGUF` (llama.cpp fork branch `mtmd-grounders`), `github.com/mudler/locate-anything.cpp` (Metal).
- Guards: `docs.ultralytics.com/models/yolo11` (+ coco.yaml class ids), `huggingface.co/PekingU/rtdetr_r18vd`, `github.com/roboflow/rf-detr`, `huggingface.co/google/owlv2-base-patch16-ensemble`, `blog.roboflow.com/florence-2`, `docs.frigate.video` (motion-gated architecture; VLM-on-thumbnails pattern).
- Glue: PyPI JSON for `desktop-notifier`/`plyer`/`notify-py`, `docs.ntfy.sh/publish`, `core.telegram.org/bots/api`, OpenCV videoio docs + issue #6039 (imshow main-thread), Python `os.fsync` docs.
- opencode: `opencode.ai/docs/providers`, `models.dev/api.json` (built-in `minimax`/`minimax-coding-plan` providers), opencode issues #31569/#32608/#11091.
