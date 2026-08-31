# LeadFlow Assistant — Production API Contract

## POST /api/chat
Accept a conversation message and return an assistant response.

Request:
```json
{"message":"What does the Professional package include?","sessionId":"optional-session-id"}
```

Response:
```json
{"reply":"...","handoff":false}
```

## POST /api/leads
Accept a lead only after explicit consent.

Required: `name`, `email`, `consent`, qualification fields.

The backend must validate input, rate-limit requests, and never expose provider API keys to the browser.

## POST /api/handoff
Create a human-handoff event containing the lead reference and conversation context. The backend is responsible for notification delivery.

## GET /api/health
Return a minimal health status. Do not expose secrets, environment variables, database credentials, or internal stack traces.

## Data rules
- Store only necessary personal information.
- Record consent timestamp.
- Retain chat/lead records for 90 days, then delete automatically.
- Human handoff triggers include explicit human requests, custom quotes/project details, frustration/negative sentiment, refunds, and complaints.

## Security
- Secrets stay in Cloudflare Worker environment/secret storage.
- Validate and sanitize all browser input server-side.
- Add rate limiting/abuse protection before public launch.
- CORS should allow only the production website origin.
