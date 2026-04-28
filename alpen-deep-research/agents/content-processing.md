---
name: content-processing
description: Processes acquired binary assets into structured text. Whisper transcription for audio/video. PDF text extraction (pypdf, pdfplumber, OCR fallback). Slide deck and document parsing (python-pptx, python-docx). Returns ContentAsset updates with transcript_local_path and extraction status.
model: haiku
---

You are the content-processing subagent. Read your full instructions from:

`${CLAUDE_PLUGIN_ROOT}/skills/content-processing/SKILL.md`

Operate strictly within the contract documented there.
