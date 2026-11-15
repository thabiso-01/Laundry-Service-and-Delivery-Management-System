# Payments with PayFast

LaundryConnect takes payments through **PayFast** (South Africa). Customers pay
on PayFast's own page, so card details never touch our servers. Development and
the automated tests use a built-in **sandbox** provider that needs no account.

## How it works

1. The customer taps **Pay** on their order. The API creates a payment for
   exactly what's owed (the order total, or the balance after weighing) and
   returns a **signed** form.
2. The browser posts that form to PayFast; the customer pays there and is sent
   back to the order page.
3. PayFast tells us the result with an **ITN** (notification) to
   `POST /api/payments/payfast/notify`. A notification only counts if:
   - its **signature** is valid (MD5 over the fields + your passphrase);
   - it comes **from PayFast's servers** (checked by IP address);
   - **PayFast confirms** it sent exactly that data (`/eng/query/validate` → `VALID`);
   - the **amount matches to the cent** (SEC-042);
   - it's for **your merchant ID**.
   Every notification – accepted or not – is stored permanently in
   `payment_events`, and duplicates are counted once.

## Set up a sandbox (test) account

1. Create a free account at **https://sandbox.payfast.co.za**.
2. In the sandbox dashboard, open **Settings → Developer Settings** and set a
   **Salt Passphrase**. Note your **Merchant ID** and **Merchant Key**.
3. In `backend/.env`:
   ```
   PAYMENT_PROVIDER=payfast
   PAYFAST_SANDBOX=true
   PAYFAST_MERCHANT_ID=...
   PAYFAST_MERCHANT_KEY=...
   PAYFAST_PASSPHRASE=...
   ```
4. Check it:
   ```bash
   cd backend
   python -m app.scripts.payfast_check
   ```
   `PayFast ACCEPTED the signed form` means the credentials and our signatures
   are right. "Generated signature does not match" means the passphrase in
   `.env` and in the dashboard differ.

> The shared test merchant `10000100` from PayFast's examples currently
> rejects signatures with its published passphrase, so use your own sandbox account.

## Receiving notifications while developing

PayFast must be able to reach `notify_url` over the internet; it can't reach
`localhost`. To test the full flow locally, expose the API with a tunnel, e.g.

```bash
cloudflared tunnel --url http://localhost:8000      # or: ngrok http 8000
```

and set `PUBLIC_API_URL` to the https address it prints. While testing through
a tunnel, the caller's IP is the tunnel's, so either start uvicorn with
`--proxy-headers --forwarded-allow-ips=*` (local testing only) or temporarily set
`PAYFAST_VERIFY_SOURCE_IP=false`. Never disable checks in production.

## Going live

1. Use your live PayFast merchant account's ID, key and passphrase.
2. Set `PAYFAST_SANDBOX=false`.
3. Set `PUBLIC_APP_URL` and `PUBLIC_API_URL` to the real https addresses.
4. Run `python -m app.scripts.payfast_check` once more.
5. Keep `PAYFAST_VERIFY_SOURCE_IP=true` and `PAYFAST_SERVER_CONFIRMATION=true`.

## Not automated yet

- **Refunds** (cancelled orders, lighter loads) are recorded as owed in the
  audit log (`payment.refund_due`) but are paid back by hand from the PayFast
  dashboard. PayFast's Refunds API can automate this later.
