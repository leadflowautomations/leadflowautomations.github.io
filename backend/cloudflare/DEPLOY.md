# LeadFlow Worker deployment

The Worker code is ready in `src/index.js` and the D1 schema is in `schema.sql`.

## One-time Cloudflare setup

1. In Cloudflare Dashboard, create a D1 database named `leadflow-leads`.
2. Apply `schema.sql` to that database.
3. Copy the database ID.
4. In `wrangler.jsonc`, replace `REPLACE_AFTER_D1_CREATE` with the real database ID.
5. Create a Cloudflare API token with permission to deploy Workers and manage D1 for this account.
6. Add these GitHub Actions repository secrets:
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`
7. Run the `Deploy LeadFlow Worker` GitHub Action manually, or push a change under `backend/cloudflare/`.

## Important

Do not commit API tokens, email credentials, or other secrets to GitHub. Keep them in GitHub Actions/Cloudflare secrets.

The current frontend expects `/api/chat` and `/api/leads` on the same origin. After the Worker is deployed, either route the API on the website's domain or update the frontend API base URL to the deployed Worker URL before the final live test.
