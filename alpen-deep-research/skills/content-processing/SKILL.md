---
name: content-processing
description: >
  USE THIS SKILL whenever cached binary assets (PDFs, audio, video, decks,
  DOCX, HTML) need to be transformed into structured markdown text via
  whisper-cli (audio/video), pypdf/pdfplumber (born-digital PDFs),
  python-pptx (decks), python-docx (Word), or tesseract OCR fallback for
  scanned PDFs. Trigger phrases include: 'transcribe this audio',
  'extract text from these PDFs', 'process the deck files', 'OCR scanned
  PDFs', 'convert binary assets to text', 'whisper the audio', 'extract
  content from these binaries', 'pdf-to-markdown these', 'process the
  cached _assets', 'run transcription on these recordings', 'extract
  pptx text'. Common in CCG, Center for BrainHealth, Krystal speaking,
  Alpen Tech research deliverables. CRITICAL: every claim of transcript
  creation must be backed by an actual file on disk; never fabricate
  transcripts. Always use this skill when cached binaries need to become
  text — do NOT pick content-acquisition (that downloads them) or
  content-analysis (that analyzes already-extracted text).
---

# content-processing

## CRITICAL RULES (NON-NEGOTIABLE)

1. **Every claim of transcript creation MUST be backed by an actual file on disk.** After every extraction, verify the transcript file exists at the expected path with non-zero bytes via Bash `ls -la` or `stat`. Never return `transcript_method: whisper-large-v3-turbo` for content you did not actually transcribe. Supported formats: pdf, audio-mp3, audio-m4a, video-mp4, pptx, docx, **html-page** (added 2026-05-07; audit finding #5).

2. **Use real extraction tools.** Whisper transcription MUST invoke `/opt/homebrew/bin/whisper-cli` via Bash. PDF extraction MUST invoke pypdf or pdfplumber via Python. OCR MUST invoke `/opt/homebrew/bin/tesseract` via Bash. Do not narrate; execute.

3. **Atomic writes.** Write transcripts to `<final_path>.tmp` first; only `mv` to the final path after extraction succeeds. Verify final file is non-empty.

4. **Validate extraction quality.** For audio/video transcripts, check that `transcript_token_count / audio_duration_seconds` is in the expected range (~2-4 tokens/sec for normal speech). For PDF extraction, check that `chars_extracted / pages` is reasonable (>500 for born-digital, may be near-zero for scanned that needs OCR). If anomalous, escalate or flag.

5. **Escalate to OCR when pypdf returns near-empty.** If pypdf or pdfplumber extracts < 100 chars per page on average, escalate to tesseract OCR. Do not just claim success on near-empty extractions.

6. **Return failure honestly.** If whisper fails, ffmpeg fails, or OCR fails, return `transcript_method: none` with explicit error in `notes`. Do not fabricate transcripts.

## Purpose

For each input asset (with `local_path` populated), produce structured text output:
- Audio/video: whisper transcription written to `<vault_root>/_assets/transcripts/<slug>.md`
- PDFs (born-digital): pypdf or pdfplumber to `<vault_root>/_assets/transcripts/<slug>.extracted.md`
- PDFs (scanned): tesseract OCR fallback when pypdf returns near-empty
- Decks: python-pptx text extraction to `<slug>.extracted.md`
- DOCX: python-docx text extraction
- HTML pages: readability extraction or html2md

Update the ContentAsset record with `transcript_local_path`, `transcript_generated_at`, `transcript_method`.

## Tools

- whisper-cli: `/opt/homebrew/bin/whisper-cli`
  - Default model: `large-v3-turbo` at `~/.cache/whisper-models/ggml-large-v3-turbo.bin`
  - Invocation: `whisper-cli -m ~/.cache/whisper-models/ggml-large-v3-turbo.bin -f <audio> -of <output-base> -otxt`
  - **IMPORTANT:** ggml's whisper-cli has `-otxt`, `-osrt`, `-oj`, `-ovtt`, `-olrc`, `-ocsv` — there is **no `--output-md` flag**. Use `-otxt` for plain prose (best for inventory/RAG); use `-osrt` only if timestamps are needed downstream.
  - Output filename: whisper writes `<output-base>.txt` (or `.srt`, etc.). Rename to `.md` after if you want markdown extension.
- pypdf, pdfplumber: Python libraries (in `~/Winnie/rag/venv` if needed)
- python-pptx, python-docx
- tesseract: `/opt/homebrew/bin/tesseract`
- ffmpeg: extract audio from video before whisper
- pdftoppm: render PDF pages to PNG for tesseract OCR

## Processing pipeline

For each asset, dispatch by `format`:

### Audio path (format: audio-mp3, audio-m4a)

```bash
SLUG=$(basename '<local_path>' | sed 's/\.[^.]*$//')
TRANSCRIPT_DIR='<vault_root>/_assets/transcripts'
TMP_BASE="${TRANSCRIPT_DIR}/${SLUG}.tmp"
FINAL_OUT="${TRANSCRIPT_DIR}/${SLUG}.md"

/opt/homebrew/bin/whisper-cli \
  -m ~/.cache/whisper-models/ggml-large-v3-turbo.bin \
  -f '<local_path>' \
  -of "$TMP_BASE" \
  -otxt -nt

# whisper-cli writes "${TMP_BASE}.txt"; rename to final .md
mv "${TMP_BASE}.txt" "$FINAL_OUT"

# Verify
ls -la "$FINAL_OUT"
wc -w "$FINAL_OUT"
```

Validate: word count vs. audio duration ratio.

### Video path (format: video-mp4)

```bash
# Extract audio first
ffmpeg -i '<local_path>' -vn -acodec libmp3lame -y '<audio_tmp>.mp3'

# Then run whisper as in audio path
```

### PDF path (format: pdf)

Try pypdf first via Python:

```bash
python3 -c "
from pypdf import PdfReader
reader = PdfReader('<local_path>')
text = ''
for page in reader.pages:
    text += page.extract_text() + '\n\n'
with open('<output_path>', 'w') as f:
    f.write(text)
print(f'Extracted {len(text)} chars from {len(reader.pages)} pages')
"
```

If `chars_extracted / pages < 100`, escalate to OCR:

```bash
# Render pages to PNG
pdftoppm -png '<local_path>' '<tmp_dir>/page'

# OCR each page
for page_png in '<tmp_dir>'/page-*.png; do
  tesseract "$page_png" - >> '<output_path>.ocr.tmp'
done

mv '<output_path>.ocr.tmp' '<output_path>'
```

### Deck path (format: pptx)

```bash
python3 -c "
from pptx import Presentation
prs = Presentation('<local_path>')
text = ''
for i, slide in enumerate(prs.slides):
    text += f'## Slide {i+1}\n'
    for shape in slide.shapes:
        if hasattr(shape, 'text') and shape.text:
            text += shape.text + '\n'
    if slide.notes_slide and slide.notes_slide.notes_text_frame:
        text += f'### Speaker notes\n{slide.notes_slide.notes_text_frame.text}\n'
    text += '\n'
with open('<output_path>', 'w') as f:
    f.write(text)
print(f'Extracted {len(text)} chars from {len(prs.slides)} slides')
"
```

### HTML path (format: html-page) — added 2026-05-07; audit findings #5, #6

68 cached HTML pages were never indexed beyond their abstract metadata before this path landed. Use `trafilatura` as primary, `readability-lxml` as fallback.

**Dependency install (PEP 668 on macOS blocks plain `pip install`; use pipx OR the project venv):**

```bash
pipx install trafilatura
pipx inject trafilatura readability-lxml
# OR, against the existing rag venv:
/Users/philhoward/Winnie/rag/venv/bin/pip install trafilatura readability-lxml
```

**Extraction:**

```bash
INPUT='<vault_root>/_assets/html/<slug>.html'
OUT_TMP='<vault_root>/_assets/transcripts/<slug>.html-extracted.md.tmp'
OUT_FINAL='<vault_root>/_assets/transcripts/<slug>.html-extracted.md'
METHOD=""

# Tier 1: trafilatura (preferred — preserves structure, drops boilerplate)
TRAF_OUT=$(/Users/philhoward/Winnie/rag/venv/bin/python3 -c "
import sys, trafilatura
html = open('$INPUT').read()
out = trafilatura.extract(html, output_format='markdown', include_comments=False, include_tables=True)
sys.stdout.write(out or '')
")
if [[ ${#TRAF_OUT} -ge 500 ]]; then
  printf '%s' "$TRAF_OUT" > "$OUT_TMP"
  METHOD="trafilatura"
else
  # Tier 2: readability-lxml fallback
  READ_OUT=$(/Users/philhoward/Winnie/rag/venv/bin/python3 -c "
from readability import Document
import sys
doc = Document(open('$INPUT').read())
sys.stdout.write(doc.summary())
")
  if [[ ${#READ_OUT} -ge 500 ]]; then
    printf '%s' "$READ_OUT" > "$OUT_TMP"
    METHOD="readability-lxml"
  else
    # Both failed; mark transcript_method=none, skip with reason='extraction-below-500-chars'
    METHOD="none"
  fi
fi

if [[ "$METHOD" != "none" ]]; then
  mv "$OUT_TMP" "$OUT_FINAL"
fi
```

Threshold: skip if extracted text < 500 chars (chrome-only artifact / auth-wall / empty page). Mark `transcript_method=none` with `notes='extraction-below-500-chars'`. Do NOT pass empty extractions downstream.

Update the parent entity's `transcript_local_path` to point at `_assets/transcripts/<slug>.html-extracted.md`. Update `content-asset.transcript_method` to `trafilatura` or `readability-lxml` per the actual path used (allowed enum values per content-asset.yaml as of 2026-05-07).

### DOCX path

```bash
python3 -c "
from docx import Document
doc = Document('<local_path>')
text = '\n'.join(p.text for p in doc.paragraphs)
with open('<output_path>', 'w') as f:
    f.write(text)
print(f'Extracted {len(text)} chars')
"
```

## Dependency-failure policy (added 2026-05-07; audit finding #14)

Caller passes `paths.dependency_policy` from the orchestrator. Two values:

| Value | Behavior on missing dependency | When to use |
|-------|-------------------------------|-------------|
| `hard-fail` (DEFAULT for production) | If a key dependency is missing or unimportable, REFUSE to process; emit `transcript_method: none`, `notes: dependency-missing-<tool>`, return status=failed for the asset. Phase D on 2026-05-07 silently fell back to a worse HTML stripper because trafilatura was unavailable; `hard-fail` is what would have caught this. | Production runs, anything that flows to dashboards/RAG. |
| `soft-fail` | Log warning, skip the asset (or fall back to a documented simpler tool); continue the batch. | Ad-hoc exploration / triage runs where partial extraction is acceptable. |

**Per-tool classification:**

| Tool | Policy |
|------|--------|
| trafilatura | hard-fail (silent extraction-quality degradation) |
| readability-lxml | hard-fail (paired fallback for trafilatura) |
| whisper-cli | hard-fail |
| pypdf / pdfplumber | hard-fail |
| python-pptx / python-docx | hard-fail |
| tesseract OCR | soft-fail (acceptable to skip a scanned page) |
| ffmpeg | hard-fail (audio extraction prerequisite) |

If running in `hard-fail` mode and a tool import fails, do NOT silently degrade. Return failure with explicit `dependency-missing-<tool>` note.

### Validation step

After every extraction, MUST run:

```bash
ls -la '<output_path>'
wc -w '<output_path>'
head -5 '<output_path>'
```

Include this output in the `verifications` field of the response.

## Output contract

```yaml
batch_id: <batch_id>
processed_assets:
  - parent_entity_slug: <slug>
    asset_id: <id>
    transcript_local_path: <path>
    transcript_generated_at: <ISO>
    transcript_method: whisper-large-v3-turbo | pypdf | pdfplumber | tesseract | python-pptx | python-docx | manual | none
    chars_extracted: <int>  # MUST match actual file size
    notes: <free-text>
extraction_failures:
  - {asset_id, reason}
verifications:
  - "ls -la output for each transcript file"
```

## Constraints

- Per-batch context budget: 50K tokens
- Per-batch turn budget: 50 turns
- Default batch size: 10 files (whisper is expensive: ~1.5x real-time on M-series Mac)
- Always write transcripts to disk before returning; never carry full transcripts in context
- Atomic writes throughout

## Tools available

- Bash (whisper-cli, ffmpeg, tesseract, pdftoppm, python invocations)
- Read, Write

## Telemetry (heartbeat + per-batch)

Whisper transcription is the slowest single operation in this pipeline (~1.5x real-time). A 30-min podcast takes ~45 min wall-clock. Heartbeats are critical so the orchestrator (and viz) know the agent is still working.

### Heartbeat events (every 60s while batch in flight)

Emit `heartbeat` periodically with current activity. For long-running whisper transcriptions, include "transcribing file 3 of 10, audio duration 2700s, elapsed 1450s."

```bash
~/Winnie/bin/hfo-log --event heartbeat \
  --skill content-processing --correlation-id "<run_id>" \
  --metrics '{"current_activity": "<one-line: transcribing audio file 3 of 10, duration 2700s, elapsed 1450s>", "batch_id": "<batch_id>", "files_processed_so_far": <int>, "elapsed_seconds": <int>}'
```

### Per-batch `skill_completed` event

After each processing batch completes, emit a `skill_completed` event via `hfo-log`. The metrics distinguish whisper transcription from PDF extraction from OCR, so the viz can show which extraction methods are most heavily used and which fail most often.

```bash
~/Winnie/bin/hfo-log \
  --event skill_completed \
  --skill content-processing \
  --department research \
  --entity ccg \
  --status <ok|partial|failed> \
  --correlation-id "<run_id>" \
  --metrics '{"client_slug": "<slug>", "batch_id": "<batch_id>", "files_processed": <int>, "transcripts_whisper": <int>, "transcripts_pypdf": <int>, "transcripts_pdfplumber": <int>, "transcripts_ocr": <int>, "transcripts_pptx": <int>, "transcripts_docx": <int>, "extraction_failures": <int>, "total_chars_extracted": <int>, "duration_s": <float>}'
```

Required even on failure. Never block real work on telemetry.
