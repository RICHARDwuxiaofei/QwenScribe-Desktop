# Gal TTS batch contract (schema 1)

A batch consists of `batch.wav` and an ordered UTF-8 `batch.jsonl`. Each JSONL row is one original voice job, in the **same order** as the Gemini TTS request's text content blocks. Do not insert audible job IDs, speaker names, scene IDs or delimiters. The source manifest is the text authority; the cutter never edits it or requests TTS.

Required fields per row:

| Field | Type | Meaning |
| --- | --- | --- |
| `job_id` | nonempty string | Unique job identity in batch |
| `character_id` | nonempty string | One character/voice per batch; `star` and `star_think` may share `star` |
| `speaker` | nonempty string | Delivery identity; may vary within one character |
| `language` | string | One language per batch: `zh-CN`, `ja-JP`, `en-US` |
| `text` | nonempty string | Exact original script / TTS text |
| `output_relpath` | relative `.wav` path | Path below selected output root (unless `target_output_relpath` is present) |

Optional `target_output_relpath` overrides `output_relpath`. It must be a safe relative `.wav` path using `/`; absolute paths, `..`, drive letters and backslashes are rejected. Other existing generator fields (`scene_id`, `line_id`, `source_text`, `source_file`, `source_line`, `segment_index`, `delivery_profile`, `emotion`, `pace`, `style_prompt`, `notes`) are accepted and left unchanged. Paths must be unique.

Example:

```jsonl
{"job_id":"zh_S01-01_star_think_0001","character_id":"star","speaker":"star_think","language":"zh-CN","text":"周六。我站在理发店门口。","output_relpath":"voice/zh/star_think/S01-01/zh_S01-01_star_think_0001.wav"}
{"job_id":"zh_S01-01_star_think_0002","character_id":"star","speaker":"star_think","language":"zh-CN","text":"我已经站了十分钟。","output_relpath":"voice/zh/star_think/S01-01/zh_S01-01_star_think_0002.wav"}
```

Optional `batch.meta.json`:

```json
{"schema_version":1,"batch_id":"zh_star_0001","audio_file":"batch.wav","jobs_file":"batch.jsonl","character_id":"star","language":"zh-CN","provider":"ai_studio","model":"gemini-3.8-flash-tts","voice_name":"Kore","request_id":null,"input_sha256":null}
```

When supplied, metadata must agree with the WAV, JSONL, character and language. `input_sha256`, if present, is the master WAV SHA-256. Inline vocal tags such as `<sigh>`, `<breath>`, `<laugh>`, `<cough>`, `<short pause>` are removed only from alignment text; the original `text` stays in reports. Such rows receive wider boundary padding and a review recommendation. Every row needs lexical speech text after tag removal.

Output is written only below a user-selected root. Reports are `alignment_report.json`, `cut_manifest.jsonl`, and `qa_report.json` in that root. Use a distinct output root per batch. Resume checks the master SHA-256, ordered jobs/text/paths, model ID, schema, cutter settings, and each output WAV SHA-256. Changed inputs are reprocessed. The cutter refuses alignment beyond 295 seconds; generate batches of at most 240 seconds where possible.

## Linux CPU execution

The Fedora 44 / Linux Gal CPU release uses the same JSONL and reports. Its Forced Aligner runs with `--device cpu` and float32; it does not provide CUDA ASR QA. It processes standard PCM master WAVs without FFmpeg and preserves their sample rate. GPU/CUDA and real TTS timing still need separate hardware validation.
