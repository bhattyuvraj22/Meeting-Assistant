# Meeting Assistant

An AI meeting assistant that takes an English meeting recording and get a raw transcript, a refined transcript, minutes, key decisions and action items in one run. If the recording does not say who owns a task or when it is due, the output says `unspecified`. It never guesses.

## Pipeline

```
audio ─► [1] Speech-to-text ─► raw transcript
                   │
                   ▼
         [2] Refinement (LLM 1) ─► refined transcript
                   │
                   ▼
         [3] Minutes, decisions, tasks (LLM 2) ─► guardrails ─► final record
```

The two language models are separate stages with separate prompts (`prompts/`).

## Two modes

The pipeline is the same in both modes. Only the models and where they run change.

| | **Mode 1: API** (default) | **Mode 2: Local** |
|---|---|---|
| Speech-to-text | Groq `whisper-large-v3` | `faster-whisper`: `large-v3` (Standard) or `small` (Lite) |
| LLM 1 (refinement) | Groq `openai/gpt-oss-20b` | Ollama: `gpt-oss:20b` (Standard) or `qwen3:4b` (Lite) |
| LLM 2 (minutes) | Groq `openai/gpt-oss-120b` | Ollama: `qwen3:14b` (Standard) or `llama3.2:3b` (Lite) |
| You need | Free [Groq API key](https://console.groq.com), internet | No API key. Standard: 16 GB+ RAM. Lite: 8 GB RAM. See the table in Mode 2 |
| Speed | Fast | Slow on CPU |
| Privacy | Audio and text are sent to Groq | Nothing leaves your machine |
| Docker command | `docker compose --profile api up --build` | `docker compose --profile local up -d --build` |
| Profile in the app | `api` | `local-docker` (Standard) or `cpu-lite-docker` (Lite) |

## Before you start: install and check

**Install Docker first.** It is the only thing you must install. Docker provides Python, ffmpeg and all packages, so you do not install them yourself.

- Windows / macOS: [Docker Desktop](https://docs.docker.com/get-docker/) (start it and wait until it says "running")
- Linux: Docker Engine with the Compose plugin

Check it works (all three must print without errors):

```bash
docker --version
docker compose version
docker info
```

Also check:

| Requirement | Mode 1 | Mode 2 |
|---|---|---|
| Free port 7860 | yes | yes |
| Internet for the first build | yes | yes (also to download models once) |
| Groq API key | **yes** | no |
| RAM (Docker Desktop: Settings → Resources → Memory must allow it) | no | **16 GB+ Standard, 8 GB Lite** |
| Free disk | ~2 GB | **~30 GB Standard, ~6 GB Lite** |

## Setup (both modes)

```bash
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>
cp .env.example .env          # Windows: copy .env.example .env
mkdir -p outputs              # Linux/macOS only
```

Mode 1 needs your keys in `.env`: paste each key right after the `=`, with no quotes and no spaces.

```
GROQ_API_KEY_STT=gsk_...
GROQ_API_KEY_LLM1=gsk_...
GROQ_API_KEY_LLM2=gsk_...
```

The three variables let each stage use its own key; the same key in all three is fine. Mode 2 does not use these keys, but keep the `.env` file. Never commit it.

### Mode 1: API

```bash
docker compose --profile api up --build
```

Open **http://localhost:7860**. The banner at the top left should be green: *Profile 'api' is ready.*

### Mode 2: Local

**Step 1. Choose an option.** Both run fully on your machine. Pick by your computer:

| Option | Profile in the app | Models | Choose it if | RAM | Disk |
|---|---|---|---|---|---|
| **Standard** | `local-docker` | Whisper `large-v3`, `gpt-oss:20b`, `qwen3:14b` | You have 16 GB+ RAM, ideally a GPU | 16 GB+ | ~30 GB |
| **Lite** | `cpu-lite-docker` | Whisper `small`, `qwen3:4b`, `llama3.2:3b` | Laptop, 8 GB RAM, no GPU | 8 GB | ~6 GB |

Lite is faster and lighter, but its transcript and minutes are less accurate. If you are not sure, start with **Lite** to see that everything works, then switch to Standard if your machine can handle it. Docker Desktop's memory limit must be at least the RAM shown.

**Step 2. Start the services** (same for both options):

```bash
docker compose --profile local up -d --build
```

**Step 3. Download the models of your option** (once; they are kept for later runs):

```bash
# Standard (~23 GB)
docker compose exec ollama ollama pull gpt-oss:20b
docker compose exec ollama ollama pull qwen3:14b

# Lite (~5 GB)
docker compose exec ollama ollama pull qwen3:4b
docker compose exec ollama ollama pull llama3.2:3b
```

**Step 4. Open http://localhost:7860** and choose your profile (`local-docker` or `cpu-lite-docker`) in the *Model profile* dropdown. The banner should say *Profile '...' is ready.* To switch option later, pull its models and change the dropdown. No rebuild is needed.

- The first transcription also downloads the Whisper model (`large-v3` ~3 GB, `small` ~0.5 GB). To do it beforehand: `docker compose --profile local run --rm app-local python download_models.py --profile local-docker` (use `cpu-lite-docker` for Lite).
- Docker on a Mac cannot use the Apple GPU, so both options run on CPU. Standard will be very slow there, so use Lite, or the "Run without Docker" route. On Linux with an NVIDIA GPU you can enable the commented `deploy:` block in `docker-compose.yml`.

### Stop and update

```bash
docker compose --profile api down        # or: --profile local down
```

`down` keeps your downloaded models. `down -v` also deletes them. After you edit `config.yaml` or any code, start again with `--build` so the image is rebuilt.

## Check that it works

1. `docker compose --profile api ps` (or `--profile local`) shows the services as running.
2. Open http://localhost:7860 (Mode 2: choose your profile first): the banner is green. A red *Fix these before running* banner lists exactly what is missing (key, model, server).
3. Process a short recording (for example the one in `sample/`). All tabs fill in and **Run details** shows the models and time per stage.
4. Look at **Run details → Warnings**. Some are normal, see Troubleshooting.

## Using the app

1. Upload a recording, or use the **Paste link** tab (YouTube, Vimeo or a direct audio link).
2. *(Optional)* Type domain terms such as `Kubeflow, OAuth` in "What is the meeting about?" to improve accuracy.
3. Click **Process recording** and watch the status box.
4. Open the tabs: **Transcripts** (raw next to refined, with a list of corrections), **Minutes**, **Decisions**, **Action items**, **Run details**.
5. Download any output, or the full record as `.md` or `.json`.

Supported: `.wav .mp3 .m4a .flac .ogg .opus .aac .wma .mp4 .webm .mkv`, English only, up to 200 MB.

### Outputs

Saved in `outputs/<date>_<time>_<id>/`:

| File | Contents |
|---|---|
| `raw_transcript.txt`, `refined_transcript.txt` | Transcript before and after term correction |
| `meeting_minutes.md` | Summary and organised minutes |
| `key_decisions.md`, `proposals.md` | Agreed decisions / ideas that were not agreed |
| `action_items.md` | Tasks with owner, deadline, status and supporting quote |
| `meeting_record.md`, `meeting_record.json` | Full record, human-readable and machine-readable (same content) |
| `run.log` | Timings, warnings, token usage |

### How the output is kept honest

Every decision and task needs a quote that really appears in the transcript. Owners and deadlines must be stated near the task, otherwise they become `unspecified`. Tentative ideas go to *Proposals*, not *Decisions*. Refinement can never change a number, a negation or a person's name.

## Troubleshooting

**Docker**

| Problem | Fix |
|---|---|
| `docker: command not found` | Install Docker (see above) |
| `Cannot connect to the Docker daemon` | Start Docker Desktop and wait until it is running |
| `no service selected` | You forgot the profile. Use `docker compose --profile api up --build` or `--profile local` |
| `env file .env not found` | Run `cp .env.example .env` |
| `port is already allocated` (7860) | Close the other program, or change `"7860:7860"` in `docker-compose.yml` to `"8080:7860"` and open port 8080 |
| Page does not open | Wait 10–20 seconds, then check `docker compose --profile api logs app` |
| `Unexpected error: PermissionError` (Linux) | `mkdir -p outputs && sudo chown 1000:1000 outputs` |
| Build fails while installing packages | Check your internet connection and run the command again |

**Mode 1: API**

| Problem | Fix |
|---|---|
| `GROQ_API_KEY_... is not set` | Add the keys to `.env`, then `docker compose --profile api up -d --force-recreate` |
| `API key ... was rejected` | The key is wrong or expired. Create a new one in the Groq console |
| `kept hitting rate limits` | Free-tier limit. Wait a minute, or use a different key per stage |
| `The request is too large` | The transcript is too big for the provider. Use a shorter recording or Mode 2 |
| `returned an error (HTTP 404)` or `rejected the request` | Groq changed a model name. Check console.groq.com/docs/models, edit `config.yaml`, rebuild with `--build` |
| `Could not get a reply ... after 5 attempts` | No internet, or the provider is down. Try again later |

**Mode 2: Local**

| Problem | Fix |
|---|---|
| `Ollama is not running` | `docker compose --profile local up -d`, then check `docker compose --profile local ps` |
| `Model not downloaded ... run ollama pull X` | Run `docker compose exec ollama ollama pull X` |
| `faster-whisper missing` | You started Mode 1. Stop it and run the Mode 2 command with `--build` |
| `GROQ_API_KEY ... is not set` | You chose profile `api`. Choose `local-docker` or `cpu-lite-docker` in the dropdown |
| `Model not downloaded` after switching option | Pull the models of the new option (Step 3) |
| Very slow, or `Could not get a reply` | CPU-only is slow, or Docker ran out of memory. Increase Docker's memory, check `docker compose --profile local logs ollama`, or switch to the Lite option (`cpu-lite-docker`) |

**Processing and output**

| Problem | Fix |
|---|---|
| `Unsupported file type` / `could not be read as audio` | Convert the file to `.mp3` or `.wav` |
| `The recording is too short` / `No speech was detected` | Check that the file plays and has speech |
| `Detected language ...` warning | The app is built for English; results may be unreliable |
| `words per minute` warning | The recording is mostly silence or music, so parts may be missing |
| `Could not download audio from that link` | The video is private, removed or blocked. Download it and upload the file instead |
| `Dropped ... (quote not found in transcript)` | Normal. A guardrail removed an item the model could not back up with a quote |
| `... set to unspecified` / `marked as suggested` | Normal. The owner, deadline or commitment was not clearly stated |
| A run failed | Anything produced before the failure is still shown. See `outputs/<run>/run.log` |

## Run without Docker (advanced)

Needs Python 3.12+ and [ffmpeg](https://ffmpeg.org/download.html) (`brew install ffmpeg` / `sudo apt install ffmpeg` / `winget install Gyan.FFmpeg`).

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # add your Groq key(s)
python app.py                                         # http://127.0.0.1:7860
python cli.py meeting.mp3 --glossary "Kubeflow, OAuth"    # or without the UI
```

For Mode 2 without Docker (uses your GPU or Apple GPU if you have one): install [Ollama](https://ollama.com), then pick the same option as above:

| Option | Profile | Download models |
|---|---|---|
| Standard | `local` | `python download_models.py --profile local --pull` |
| Lite | `cpu-lite` | `python download_models.py --profile cpu-lite --pull` |

```bash
pip install -r requirements-local.txt
# run the download command for your option (table above)
OLLAMA_CONTEXT_LENGTH=32768 ollama serve
python app.py            # choose your profile in the dropdown, or: python cli.py meeting.mp3 --profile cpu-lite
```

## Tests

```bash
pip install -r requirements-dev.txt
ruff check . && pytest -q
```

The tests use fake models, so they need no API key. GitHub Actions runs them on every push.

## Limitations

English only. The transcript has no speaker labels, so "I'll do it" with no name nearby gives an owner of `unspecified` on purpose. Refinement is conservative and may leave a mis-heard term uncorrected rather than risk changing the meaning. Noisy audio and overlapping speakers lower accuracy.