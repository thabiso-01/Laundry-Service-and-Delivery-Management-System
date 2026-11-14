// One order from search to delivery, clicked through the real screens by all
// five people (UAT-001 – UAT-011), each in their own browser session.

import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const PASSWORD = "DemoPass#2026";
const HOME = { latitude: -26.2041, longitude: 28.0473 };
const LAUNDRY = { latitude: -26.1929, longitude: 28.0305 };
const SHOTS = "e2e/screenshots";

// Address search is faked in the browser: tests never call OpenStreetMap
async function fakeGeocoder(page: Page) {
  const address = {
    label: "12 Pritchard Street, Marshalltown, Johannesburg", address_line: "12 Pritchard Street",
    suburb: "Marshalltown", city: "Johannesburg", province: "Gauteng", postal_code: "2001", ...HOME,
  };
  await page.route("**/api/geocode/reverse**", (r) => r.fulfill({ json: address }));
  await page.route(/\/api\/geocode\?/, (r) => r.fulfill({ json: [address] }));
}

// Fail the test on any uncaught error in the page
function watchErrors(page: Page, errors: string[]) {
  page.on("pageerror", (e) => errors.push(`${page.url()}: ${e.message}`));
}

async function session(browser: Browser, where: { latitude: number; longitude: number }, errors: string[]) {
  const context = await browser.newContext({ geolocation: where, permissions: ["geolocation"] });
  const page = await context.newPage();
  watchErrors(page, errors);
  await fakeGeocoder(page);
  return { context, page };
}

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).not.toHaveURL(/\/login$/);
}

// The bag label code, read the way a scanner would get it (the QR image's text)
async function bagCode(page: Page, orderId: string): Promise<string> {
  return page.evaluate(async (id) => {
    const token = sessionStorage.getItem("lc_token");
    const r = await fetch(`/api/business/orders/${id}/qr?format=text`, { headers: { Authorization: `Bearer ${token}` } });
    return (await r.json()).code as string;
  }, orderId);
}

async function goOnline(page: Page) {
  const button = page.getByRole("button", { name: "Go online" });
  if (await button.isVisible()) await button.click();
  await expect(page.getByRole("button", { name: "Go offline" })).toBeVisible();
}

// Let pictures and map tiles finish loading before a screenshot
async function settled(page: Page) {
  await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => undefined);
}

const seal = () => `E2E${Date.now().toString(36).toUpperCase()}${Math.floor(Math.random() * 1000)}`;

test("customer → laundry → drivers → delivered, all through the screens", async ({ browser }) => {
  const errors: string[] = [];
  const contexts: BrowserContext[] = [];
  const open = async (where: typeof HOME) => {
    const s = await session(browser, where, errors);
    contexts.push(s.context);
    return s.page;
  };

  // ---------- Customer finds a laundry and orders ----------
  const customer = await open(HOME);
  await login(customer, "customer@demo.lc");
  await expect(customer).toHaveURL(/\/search/);
  await customer.getByRole("button", { name: /Use my location/ }).click();
  await customer.getByRole("link", { name: /Braam Fresh Laundry/ }).first().click();
  await expect(customer.getByRole("heading", { name: "Braam Fresh Laundry" })).toBeVisible();

  await customer.getByLabel("Quantity of Wash & Fold").fill("5");
  await customer.getByRole("button", { name: /Use my current location/ }).click();
  await expect(customer.getByLabel("Street address")).toHaveValue("12 Pritchard Street");
  await customer.getByRole("button", { name: "See price" }).click();
  await expect(customer.getByText(/Total/).last()).toBeVisible();
  await settled(customer);
  await customer.screenshot({ path: `${SHOTS}/01-customer-checkout.png`, fullPage: true });
  await customer.getByRole("button", { name: "Place order" }).click();
  await expect(customer).toHaveURL(/\/orders\/[0-9a-f-]{36}$/);
  const orderId = customer.url().split("/").pop()!;
  const orderNumber = (await customer.locator("h1").first().textContent())!.trim();

  await customer.getByRole("button", { name: /^Pay R/ }).click();
  await expect(customer.getByRole("button", { name: /^Pay R/ })).toHaveCount(0);
  await settled(customer);
  await customer.screenshot({ path: `${SHOTS}/02-customer-paid.png`, fullPage: true });

  // ---------- Laundry accepts ----------
  const owner = await open(LAUNDRY);
  await login(owner, "owner@demo.lc");
  await owner.getByRole("link", { name: new RegExp(orderNumber) }).click();
  await owner.getByRole("button", { name: "Accept order" }).click();
  await expect(owner.getByText("Accepted").first()).toBeVisible();

  // Customer now sees the collection code
  await customer.reload();
  const codeBox = customer.locator("p.font-mono.text-4xl");
  await expect(codeBox).toHaveText(/^\d{6}$/);
  const collectionCode = (await codeBox.textContent())!;
  await settled(customer);
  await customer.screenshot({ path: `${SHOTS}/03-customer-collection-code.png`, fullPage: true });

  // ---------- Driver 1 collects ----------
  const driver1 = await open(HOME);
  await login(driver1, "driver1@demo.lc");
  await goOnline(driver1);
  await driver1.getByRole("button", { name: "Accept" }).first().click();
  await expect(driver1).toHaveURL(/\/driver\/jobs\//);
  await settled(driver1);
  await driver1.screenshot({ path: `${SHOTS}/04-driver-job.png`, fullPage: true });
  const collectionSeal = seal();
  await driver1.getByLabel("Seal number(s) you put on the bag").fill(collectionSeal);
  await driver1.getByLabel("Customer's collection code").fill(collectionCode);
  await driver1.getByRole("button", { name: "Confirm collection" }).click();
  await expect(driver1.getByText("Done ✔")).toBeVisible();

  // ---------- Laundry receives, weighs, cleans ----------
  await owner.reload();
  const code = await bagCode(owner, orderId);
  await owner.getByLabel("Bag label code").fill(code);
  await owner.getByLabel("Seal numbers on the bag").fill(collectionSeal);
  await owner.getByRole("button", { name: "Confirm received" }).click();
  await expect(owner.getByRole("button", { name: "Start processing" })).toBeVisible();
  await owner.getByRole("button", { name: "Save weights" }).click();
  await owner.getByRole("button", { name: "Start processing" }).click();
  await owner.getByRole("button", { name: "Mark ready for delivery" }).click();
  await expect(owner.getByText(/A driver will collect the bag/)).toBeVisible();
  await settled(owner);
  await owner.screenshot({ path: `${SHOTS}/05-laundry-order.png`, fullPage: true });

  // ---------- Driver 2 delivers ----------
  const driver2 = await open(LAUNDRY);
  await login(driver2, "driver2@demo.lc");
  await goOnline(driver2);
  await driver2.getByRole("button", { name: "Accept" }).first().click();
  await expect(driver2).toHaveURL(/\/driver\/jobs\//);
  await driver2.getByLabel("Bag label code").fill(code);
  await driver2.getByLabel("Seal number(s) on the clean bag").fill(seal());
  await driver2.getByRole("button", { name: "Confirm pickup" }).click();
  await expect(driver2.getByText("Done ✔")).toBeVisible();

  await customer.reload();
  await expect(customer.getByText("Delivery code")).toBeVisible();
  const deliveryCode = (await customer.locator("p.font-mono.text-4xl").textContent())!;
  expect(deliveryCode).not.toBe(collectionCode);

  // Driver 2 drives to the customer before handing over
  await driver2.context().setGeolocation(HOME);
  await driver2.getByLabel("Customer's delivery code").fill(deliveryCode);
  await driver2.getByRole("button", { name: "Confirm delivery" }).click();
  await expect(driver2.getByText("Done ✔")).toBeVisible();

  // ---------- Customer sees it all and leaves a review ----------
  await customer.reload();
  await expect(customer.getByText("Delivered").first()).toBeVisible();
  await expect(customer.getByText("Delivered to customer")).toBeVisible();
  // Every handover happened where it should: nothing flagged
  await expect(customer.getByText("location flagged")).toHaveCount(0);
  await expect(customer.getByText("Intact")).toHaveCount(2);
  await expect(customer.getByText("R185.00").first()).toBeVisible();
  await customer.getByRole("button", { name: "Submit review" }).click();
  await expect(customer.getByLabel("What are you rating?")).not.toContainText("The laundry");
  await settled(customer);
  await customer.screenshot({ path: `${SHOTS}/06-customer-delivered.png`, fullPage: true });

  // Notifications reached the customer
  await customer.goto("/notifications");
  await expect(customer.getByText("Delivered").first()).toBeVisible();

  // ---------- Admin screens render ----------
  const admin = await open(HOME);
  await login(admin, "admin@demo.lc");
  await expect(admin.getByRole("heading", { name: "Verification" })).toBeVisible();
  await admin.goto("/admin/incidents");
  await expect(admin.getByRole("heading", { name: "Incidents" })).toBeVisible();
  await admin.goto("/admin/routes");
  await expect(admin.getByRole("heading", { name: "Route alerts" })).toBeVisible();
  await settled(admin);
  await admin.screenshot({ path: `${SHOTS}/07-admin-routes.png`, fullPage: true });

  for (const c of contexts) await c.close();
  expect(errors, "uncaught errors in the pages").toEqual([]);
});

test("pages work on a phone-sized screen", async ({ browser }) => {
  const errors: string[] = [];
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  watchErrors(page, errors);
  await page.goto("/search");
  await expect(page.getByRole("link", { name: /Braam Fresh Laundry/ }).first()).toBeVisible();
  // No sideways scrolling on a phone (NFR-007)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await settled(page);
  await page.screenshot({ path: `${SHOTS}/08-phone-search.png`, fullPage: true });
  await context.close();
  expect(errors).toEqual([]);
});
