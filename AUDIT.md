# Pre-change audit — 2026-10-12

The original directory contains Python sources, exported n8n workflows, SQL schemas,
a Python 3.12 virtual environment, existing tests, local secrets, invoice uploads,
research outputs, logs and two archives. The .git directory contains no usable Git
repository; no commits or remotes were available to inspect. No AGENTS.md was found.

## Verified implementation

- FastAPI entry point: api:app. Health, invoice processing, research execution and report download endpoints.
- Invoices: PyMuPDF text extraction, Tesseract fallback with Arabic/Persian digit normalization,
  multimodal Gemini extraction with Groq fallback, Pydantic models, retrying incomplete
  extraction, arithmetic/mandatory-field validation, Google Sheets and Supabase writes,
  SHA256 duplicate lookup.
- Research: SerpAPI with Tavily fallback, concurrent Playwright Chromium fetching,
  blocked/short-page filtering, concurrent LLM summaries, consolidated report generation,
  Arabic/English language routing and Markdown/HTML/WeasyPrint PDF exports.
- Two n8n exports: Google Drive invoice trigger/download and Gmail notification;
  form-based research, HTTP report download, Gmail delivery and Drive upload.
  These are exported configurations, not evidence of successful deployment.
- Docker Compose hosts n8n only, backed by a named volume. Python API runs on the host.

## Findings before changes

- README is outdated: nonexistent CLI entry points and claims that workflow exports are missing.
- Broken research-test imports and invoice mock interface; valid fixture lacks a mandatory date.
- Runtime requirements omit FastAPI, Uvicorn, multipart parser, Loguru and Google clients.
- Sheets writer embeds a service-account filename and spreadsheet identifier and writes untrusted
  strings with USER_ENTERED, which can interpret spreadsheet formulas.
- LLM module raises during import without a Gemini key; model defaults disagree between modules.
  DEFAULT_LLM_PROVIDER, OpenAI and Anthropic configuration does not select implemented providers.
- Extraction prompt contradicts schema/validation about whether total_amount includes tax.
- Omitted line totals do not trigger the Pydantic computation validator.
- Legacy PostgreSQL writer references missing settings.database_url and is not used by api.py.
  Drive polling is an explicit unimplemented stub.
- API has no authentication, upload-size restrictions or research-result bounds; errors expose
  exception details. Blocking work runs inside the asynchronous invoice route.
- HTML interpolates untrusted content; PDF renderer can fetch URLs or local resources.
- Supabase schema does not enable RLS. Duplicate lookup fails open and parallel uploads can race.
- n8n exports include personal/account references and potentially pinned execution data.
  Compose binds all interfaces and enables otherwise disabled nodes.
- No license is present; none will be added without owner approval.

Complete backup: /tmp/ai-agents-hub-preparation/original-backup.tar.gz.
All preparation takes place in a separate publishing copy. Original files remain intact.
