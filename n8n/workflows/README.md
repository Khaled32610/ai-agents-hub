# n8n workflow templates

Import `Invoice Extractor.json` or `Web Research.json` into your own n8n instance.
Both exports are inactive. Credential bindings, pinned executions, personal addresses,
instance metadata and account folder IDs have been removed.

The invoice workflow polls a configured Google Drive folder, downloads a file,
posts it to `/invoices/process`, then sends a notification on validation failure
or duplicate detection. Replace the folder placeholder, bind Drive/Gmail credentials,
and choose the notification recipient. The default operator@example.com is synthetic.
Review the customer-email expression before enabling automatic delivery.

The research workflow accepts a form submission, calls `/research/run`, asks for
language clarification when required, splits report_paths, downloads each report
and sends/uploads it through Gmail and Google Drive. Configure the destination folder
and all credential bindings. Delivery and workflow execution have not been tested.

HTTP nodes use http://host.docker.internal:8000. On Linux, Compose supplies the host-gateway
mapping. The API must listen on an interface reachable from Docker; protect this
interface with a firewall and an authenticated reverse proxy. Default README startup
binds localhost and is for direct local use only. Do not expose the API publicly.

Compose preserves the n8n image's default node restrictions. No Execute Command or
Local File Trigger is needed for these exports. The image still uses latest; pin a
reviewed image digest before a reproducible deployment.
