# LeadFlow Cloudflare deployment checklist

This file documents the required production wiring without changing application behavior.

## Required Worker

- Worker: `leadflow-assistant-api`
- D1 database: `leadflow-leads`
- D1 binding variable: `DB`

## Required API routes

- `GET /api/health`
- `POST /api/leads`
- `POST /api/chat`
- `POST /api/handoff`

## Consultation flow

The production website must submit consultation requests to the Cloudflare Worker API and receive a successful JSON response. A deployment is not considered complete until a real request is accepted by the Worker and persisted in D1.
