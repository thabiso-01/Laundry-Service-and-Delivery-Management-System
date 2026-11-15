// POPIA rights through the screens: download my data, then delete my account.

import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

test("a new customer downloads their data and deletes their account", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const email = `e2e-${Date.now()}@example.com`;
  const password = "E2ePrivacy#2026";

  // Register through the form
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Privacy Tester");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByLabel(/I agree to the privacy policy/).check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/search/);

  // Download my data (POPIA s23)
  await page.goto("/security");
  await expect(page.getByRole("heading", { name: "Account & privacy" })).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download my data" }).click(),
  ]);
  const data = JSON.parse(readFileSync((await download.path())!, "utf8"));
  expect(data.account.email).toBe(email);
  expect(data.account.full_name).toBe("Privacy Tester");

  // Delete my account (POPIA s24)
  const deleteButton = page.getByRole("button", { name: "Delete my account permanently" });
  await page.getByLabel("Password").fill(password);
  await expect(deleteButton).toBeDisabled(); // needs the typed confirmation
  await page.getByLabel("Type DELETE to confirm").fill("DELETE");
  await deleteButton.click();
  await expect(page.getByText("Your account has been deleted")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/09-account-deleted.png" });

  // The old login no longer works
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("Incorrect email or password")).toBeVisible();

  expect(errors).toEqual([]);
});
