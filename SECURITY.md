# Security review

Prepared on 2026-10-12. This is a local portfolio prototype, not a hardened public service.

## Publication boundary

The original `.env` and `secrets/` service-account JSON contain credentials identified
by Gitleaks. Their values were never printed or copied into the publishing repository.
Original invoice inputs, research reports, logs, archives and virtual environments
are also excluded. Gitleaks reports for the original remain private outside the repo.
There was no usable original Git history. A new publishing repository has its full
history scanned before any push. No remote has been created.

Because no committed credentials were found, no history rewrite is needed for this
new repository. Rotate credentials if the original archives or files were previously
shared elsewhere. The complete backup contains sensitive data and must remain private.

## Mitigations in this copy

- Placeholder-only environment example and explicit excludes for local data/secrets.
- Environment-based Sheets destination and credentials; RAW cells prevent formula execution.
- Public HTTP(S) browser destinations only, with DNS checks on navigation and routed requests.
- Escaped HTML output; escaped raw HTML in Markdown-to-PDF conversion; all PDF URL fetching denied.
- Upload extension and 20 MiB limits, 20 PDF-page cap, bounded research inputs, private temporary
  rendered images with cleanup, closed PDF/image handles, generic API error responses.
- Prompt instructions label documents/articles as untrusted; schema and deterministic validation.
- Supabase RLS enabled and access revoked from anon/authenticated roles. No permissive policy added.
- Inactive, sanitized n8n templates, localhost n8n port binding and default node restrictions.

## Remaining boundaries

The API has no authentication or user ownership checks and exposes all reports to
any caller with access. Run locally or behind authenticated network controls. Do not
expose port 8000 publicly. DNS checks are defense in depth and do not replace egress
firewalling against rebinding or browser-network edge cases. Limit CPU, memory and
request duration at deployment; uploads can still be malformed or decompression bombs.

LLM content can still induce false extractions/summaries despite instructions.
Review outputs before business use. Provider responses, exceptions and document
fields can appear in private logs. Service-role credentials are privileged and
must never be given to clients. Duplicate checks fail open; writes across Sheets
and Supabase are nontransactional and can race. No arbitrary Python execution or
LLM-generated SQL was found. Legacy parameterized PostgreSQL code was removed only
from the publishing copy because it is unused and references missing configuration.

The Gemini SDK is deprecated; provider/model availability and live integrations are
not verified. Dependency scanning reports known advisories only, not proof of safety.
