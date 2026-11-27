# Choosing a Whisper model

Voice Input uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) models (Whisper
converted to CTranslate2). Set the model with `model = "…"` in the configuration, per language with
the `[models]` table, or try one quickly with `voice-input transcribe --model NAME file.wav`.

The default is **`small`**: on a laptop CPU it recognises a sentence in about two seconds and is
accurate for English and Russian. Larger models are more accurate, especially for Hebrew, but on a
CPU they take several seconds per sentence; with a CUDA GPU they are fast.

## Measurements

Machine: Intel Core i7-1165G7 (4 cores, 8 threads), no GPU, `compute_type = int8`,
CTranslate2 4.9.1, faster-whisper 1.2.1, `beam_size = 5`, VAD on, model already loaded.
Audio: one synthesised sentence per language (Kokoro for English, Piper for Russian and Hebrew),
5–8 seconds long.

| Model | Download | English (6.3 s) | Russian (8.0 s) | Hebrew (5.4 s) |
|---|---|---|---|---|
| `base` | ~145 MB | 0.7 s | 0.7 s | 0.8 s |
| **`small`** (default) | ~485 MB | 1.7 s | 1.9 s | 2.1 s |
| `medium` | ~1.5 GB | 4.9 s | 5.6 s | 5.8 s |
| `large-v3-turbo` | ~1.6 GB | 6.9 s | 6.6 s | 6.8 s |
| `ivrit-ai/whisper-large-v3-turbo-ct2` (Hebrew) | ~1.6 GB | — | — | 9.1 s |

`beam_size = 1` changed the times by less than 10% on this machine.

What the models got right on these samples:

- **English:** every model transcribed the sentence exactly, with punctuation.
- **Russian:** every model wrote the sentence correctly except one word that the synthetic voice
  pronounces unclearly ("ввода" heard as "года"); `large-v3-turbo` with beam size 1 got it right.
- **Hebrew:** all models produced the sentence with one or two misspelt words. The synthetic
  Hebrew voice is of medium quality, so this says little about real speech.

Synthetic voices are a convenient, repeatable test but not a substitute for your own voice and
microphone: try `voice-input listen --model …` before deciding.

## Recommendations

| Situation | Setting |
|---|---|
| Laptop or desktop CPU (most people) | `model = "small"` (default) |
| Slow or old CPU, short notes | `model = "base"` |
| CUDA GPU | `model = "large-v3-turbo"` (fast on a GPU, best general accuracy) |
| Lots of Hebrew dictation | `[models] he = "ivrit-ai/whisper-large-v3-turbo-ct2"` — fine-tuned on Hebrew by [ivrit.ai](https://huggingface.co/ivrit-ai); expect several seconds per sentence on a CPU |
| Accuracy matters more than speed (CPU) | `model = "medium"` |

A per-language model is only loaded when that language is used, and stays in memory afterwards.
With `language = "auto"`, the default model detects the language first and the language's own model
then recognises the audio, so a Hebrew dictation costs both.

English-only models (`small.en`, `base.en`, `distil-large-v3`) cannot recognise Russian or
Hebrew; use them only together with per-language models.

## Memory

Roughly, with int8 on the CPU: `base` 200 MB, `small` 500 MB, `medium` 1.2 GB, `large-v3-turbo`
1.5 GB of RAM while the daemon runs. Each additional per-language model adds its own share.

## Licences

The OpenAI Whisper weights (and their faster-whisper conversions) are MIT licensed. Third-party
fine-tunes have their own licences; check the model card before use.
