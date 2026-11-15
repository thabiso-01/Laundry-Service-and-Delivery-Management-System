# SMS notifications

Every notification appears in the in-app inbox. The most important ones are
also sent by SMS to users who have a mobile number and haven't switched SMS off
(*Account & privacy → Text messages*):

| Notification | Why it's worth an SMS |
|---|---|
| Driver on the way (collection or delivery) | The customer needs to be home |
| Out for delivery | Have the delivery code ready |
| Delivered | Confirmation the bag arrived |
| Order declined | The customer must re-order elsewhere |
| Balance to pay after weighing | Delivery waits for it |
| Account locked, new-device sign-in, two-step login turned off | Security (SEC-045) |

One-time codes are **never** sent by SMS; they're only shown in the app.

## How it works

- Messages are queued (`notifications.sms_status = pending`) in the same
  database transaction as the event, and a background worker in the API
  process sends them every 15 seconds, after the transaction has committed.
- Failed sends are retried 3 times with the same BulkSMS `deduplication-id`, so
  a retry never sends a duplicate; then they're marked `failed` with the reason.
- At most 10 SMS per user per day (`SMS_MAX_PER_USER_PER_DAY`) to protect the
  bill. Messages older than 24 hours are not sent late.
- Texts are capped at 306 characters (two SMS segments) and kept to plain GSM
  characters where possible.

## Development

`SMS_PROVIDER=log` (the default) only writes messages to the server log.

## Using BulkSMS

1. Create an account at https://www.bulksms.com and buy some credits.
2. Create an API token: **Settings → Developer Settings → API Tokens**.
3. In `backend/.env`:
   ```
   SMS_PROVIDER=bulksms
   BULKSMS_TOKEN_ID=...
   BULKSMS_TOKEN_SECRET=...
   ```
4. Send yourself one test SMS (costs one credit):
   ```bash
   cd backend
   python -m app.scripts.sms_check --to "082 123 4567"
   ```

To use another provider (e.g. Clickatell), add a send function next to
`_send_bulksms` in `app/services/sms.py` and register it in `PROVIDERS`.

If you run several API processes, they can all run the worker safely (queued
rows are locked while being sent), or set `SMS_WORKER_ENABLED=false` on all but
one.
