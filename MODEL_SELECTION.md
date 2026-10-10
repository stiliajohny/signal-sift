# Small local model selection

Researched on 2026-10-10 using publisher and Ollama documentation. Download sizes are current registry listings, not RAM/VRAM requirements or guarantees of latency. Tags may change; record the downloaded manifest digest and pin approved copies for a controlled deployment.

## Selected default: Qwen3 1.7B

`MODEL_NAME=qwen3:1.7b`, served by the local Ollama native `/api/chat` API.

The [official Ollama listing](https://ollama.com/library/qwen3:1.7b) gives a package size of approximately **1.4 GB**, Q4_K_M quantisation and text input. That fits this prototype's constrained role: describe already-collected evidence, propose advisory priority, identify missing information, and recommend checks. It avoids downloading image/audio components that this text-only pipeline does not use.

This is a deployment-fit recommendation, **not a result showing that this model is more accurate at alert triage**. Its operational reasoning can be wrong even when its JSON is valid. It should not decide whether to discard important alerts.

## Compared candidates

| Candidate | Listed package size | Decision |
|---|---:|---|
| Qwen3 `1.7b` | 1.4 GB | Default: small text-only candidate |
| Qwen3.5 `2b-q4_K_M` | 1.9 GB | Newer comparison candidate if the default gives weak explanations |
| Qwen3.5 `0.8b-q8_0` | 1.0 GB | Smaller footprint candidate for a very constrained demo; quality must be evaluated |
| Gemma 4 `e4b-it-q4_K_M` | 6.6 GB | Larger than the requested demo footprint |
| Granite 4 `1b` | 3.3 GB (BF16 listing) | Default named tag is not as compact; not selected |

Sources: [Qwen3 listing](https://ollama.com/library/qwen3:1.7b), [Qwen3.5 tags](https://ollama.com/library/qwen3.5/tags), [Gemma tag](https://ollama.com/library/gemma4:e4b-it-q4_K_M), [Granite tag](https://ollama.com/library/granite4:1b). Exact quantisation matters: the generic Qwen3.5 `2b` tag has a larger listed package than `2b-q4_K_M`; parameter count alone is not a reliable download-size comparison.

The [Qwen3.5-2B publisher model card](https://huggingface.co/Qwen/Qwen3.5-2B) identifies prototyping/research/task-specific tuning as intended uses at this scale. Its published comparison reports different rankings by task and thinking mode. Those benchmarks do not measure Kubernetes alert noise, and do not establish the best model for this project. No model was downloaded or benchmarked on actual telemetry in this authoring environment.

## Serving choices

[Ollama structured-output documentation](https://docs.ollama.com/capabilities/structured-outputs) supports passing a JSON schema in `format`; it recommends Pydantic validation and low temperature. The worker supplies the schema both in the prompt and in `format`, with `stream=false` and `think=false`. Schema enforcement improves formatting; it does not prove evidence interpretation is correct.

[Native chat API](https://docs.ollama.com/api/chat): final text is in `message.content`. The app does not store the separate thinking field. Generation is bounded by `num_predict`; context is configured by `num_ctx`. Character budgeting is an interim safeguard, not an approved exact tokenizer count. Check serving-side truncation when integrating the real tokenizer/model.

[Docker instructions](https://docs.ollama.com/docker) cover CPU and NVIDIA execution. Default Compose uses CPU; `compose.gpu.yaml` is an optional NVIDIA override. Ollama is pinned to image tag `0.40.2`, the release returned by [the official releases page](https://github.com/ollama/ollama/releases/tag/v0.40.2) during research. Image digests are not pinned yet.

[Ollama FAQ](https://docs.ollama.com/faq) documents `OLLAMA_NO_CLOUD=1`. This is set on the server and pull service. No cloud tag is configured, and the Python settings reject cloud tags for native Ollama. Initial image/weight/dependency acquisition still requires registry access.

## How to choose on your own data later

Keep the collector evidence identical and review representative recovered pod failures, sustained replica loss, HPA saturation with/without user impact, missing logs, stale metrics and repeated pages. Compare factual claims/citations, missing-evidence handling, missed urgency, JSON validity, latency and actual memory on your hardware. Human-labelled incidents should determine whether a model is adequate. Frequency is not a noise label. There is no claim that the 1.7B candidate matches your approved 120B work model.

For production work use the already-approved internal model endpoint; the small model is the local demonstration option requested in this conversation. Model selection/licensing and telemetry access remain your organisation's configuration decisions.
