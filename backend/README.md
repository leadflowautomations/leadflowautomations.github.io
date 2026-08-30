# LeadFlow Assistant — secure backend

This directory is the backend contract for LeadFlow Assistant.

## Production architecture

The GitHub Pages frontend must never contain AI API keys, SMTP credentials, database credentials, or other secrets.

A server-side endpoint should eventually expose:

- `POST /api/chat` — send a visitor message plus safe conversation context; return an AI response.
- `POST /api/leads` — accept a lead only after affirmative consent.
- `POST /api/handoff` — send a human-handoff request containing the minimum necessary lead details and transcript.
- `GET /api/health` — health check.

## Lead payload

```json
{
  "name": "string",
  "email": "string",
  "phone": "string|null",
  "businessName": "string|null",
  "businessType": "string",
  "need": "string",
  "packageInterest": "string",
  "timeline": "string",
  "consent": true,
  "consentTimestamp": "ISO-8601 timestamp",
  "conversationId": "string"
}
```

## Required safeguards

1. Reject lead submissions without affirmative consent.
2. Validate and sanitize all fields server-side.
3. Rate-limit chat and lead endpoints.
4. Keep API credentials in server-side environment secrets only.
5. Do not expose provider keys to browser JavaScript.
6. Retain chat logs for no longer than 90 days, then delete automatically.
7. Send human handoffs to `leadflowautomation.dav@gmail.com`.
8. Never let the model invent pricing, delivery times, capabilities, refunds, or integrations; use the business specification as the source of truth.

## Current status

The frontend qualification layer is ready. A hosting/runtime provider is required for this server-side layer before real AI, persistent lead storage, and automatic email handoff can be enabled.
