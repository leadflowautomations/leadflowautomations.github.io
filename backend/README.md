# Lead Flow Automation Backend

This folder contains the server-side foundation for LeadFlow Assistant.

## Current components

- `worker.js` — Cloudflare Worker API scaffold.
- `schema.sql` — Cloudflare D1 schema for leads and chat logs.

## Planned production flow

1. Website sends approved lead data to `/api/leads`.
2. Worker validates origin, input, and consent.
3. D1 stores the lead.
4. AI conversation handling is added server-side so provider credentials are never exposed in the browser.
5. Human handoff sends the transcript and lead details to `leadflowautomation.dav@gmail.com`.
6. A scheduled retention process removes chat records after 90 days.

## Security notes

Never commit API keys, email credentials, database credentials, or other secrets to this repository. Configure secrets/bindings in Cloudflare instead.
