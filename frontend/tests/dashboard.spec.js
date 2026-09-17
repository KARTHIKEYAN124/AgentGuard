import { test, expect } from "@playwright/test";

test("workspace to trace, regression report, experiment, and responsive dashboard", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Agent performance" }),
  ).toBeVisible();
  await expect(
    page.getByText("This read-only demo uses sample agents", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Create your workspace", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page.getByLabel("Your name").fill("Evaluation team");
  await page.getByLabel("Email address").fill("evaluation-team@example.com");
  await page
    .getByLabel("Password", { exact: true })
    .fill("Long testing password 123!");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "Load demo workspace" }).click();
  await expect(
    page.getByRole("button", { name: "Load demo workspace" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Execute agent", exact: true })
    .click();
  await page.getByRole("button", { name: "Execute & trace" }).click();
  await expect(
    page.getByRole("heading", { name: "Execution timeline" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "You can return an unused item within 30 days of delivery.",
      { exact: true },
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: /llm.generate/ }).click();
  await expect(page.locator("pre").first()).toContainText("input_tokens");
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.getByRole("button", { name: "Run evaluation" }).click();
  await page.getByRole("button", { name: "Run suite", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: /Evaluation · customer-support/ }),
  ).toBeVisible();
  await expect(page.getByText("Accuracy 100.0%")).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export report" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/agentguard-.*\.json/);
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.getByRole("button", { name: "Experiments", exact: true }).click();
  await page
    .getByRole("button", { name: "Create experiment", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Create experiment" })
    .click();
  await expect(page.getByText("Support version comparison")).toBeVisible();
  await page.getByRole("button", { name: "Results", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "Descriptive metrics only",
  );
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.getByRole("button", { name: "Prompts", exact: true }).click();
  await page.getByRole("button", { name: "View evaluations" }).first().click();
  await expect(page.getByRole("dialog")).toContainText("evaluation evidence");
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.getByRole("button", { name: "Traces", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Search traces" })
    .fill("no-such-agent");
  await expect(
    page.getByText("No traces yet.", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await page.screenshot({
    path: "../.qa/dashboard-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Agent performance" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../.qa/dashboard-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await page.getByRole("button", { name: "Agents", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Agent registry" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("private signup, invitation acceptance, viewer restrictions, and usage controls", async ({
  browser,
  baseURL,
}) => {
  const ownerContext = await browser.newContext();
  const memberContext = await browser.newContext();
  const owner = await ownerContext.newPage();
  const member = await memberContext.newPage();
  async function register(page, name, email) {
    await page
      .getByRole("button", { name: "Create an account", exact: true })
      .click();
    await page.getByLabel("Your name").fill(name);
    await page.getByLabel("Email address").fill(email);
    await page
      .getByLabel("Password", { exact: true })
      .fill("Long testing password 123!");
    await page
      .getByRole("button", { name: "Create account", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Create your account" }),
    ).toHaveCount(0);
  }
  await owner.goto(baseURL);
  await owner
    .getByRole("button", { name: "Create your workspace", exact: true })
    .click();
  await register(owner, "Team owner", "team-owner@example.com");
  await owner.getByRole("button", { name: "Load demo workspace" }).click();
  await expect(
    owner.getByRole("button", { name: "Load demo workspace" }),
  ).toHaveCount(0);
  await owner
    .getByRole("button", { name: "Workspace & account", exact: true })
    .click();
  await owner.getByLabel("Teammate email").fill("invited-viewer@example.com");
  await owner
    .getByRole("button", { name: "Create invitation", exact: true })
    .click();
  const link = owner.getByLabel("Private invitation link");
  await expect(link).toBeVisible();
  const invitation = await link.inputValue();
  await member.goto(invitation);
  await member
    .getByRole("button", { name: "Sign in to accept", exact: true })
    .click();
  await register(member, "Team viewer", "invited-viewer@example.com");
  await member
    .getByRole("button", { name: "Accept invitation", exact: true })
    .click();
  await expect(
    member.getByText("Viewer access", { exact: false }),
  ).toBeVisible();
  await member.getByRole("button", { name: "Agents", exact: true }).click();
  await expect(
    member.getByText("customer-support", { exact: true }).first(),
  ).toBeVisible();
  await member
    .getByRole("button", { name: "Register agent", exact: true })
    .click();
  await expect(member.getByRole("alert")).toContainText(
    "viewer role is read-only",
  );
  await owner.getByRole("button", { name: "Close dialog" }).click();
  await owner
    .getByRole("button", { name: "Workspace & account", exact: true })
    .click();
  await owner
    .getByRole("button", { name: "Usage & limits", exact: true })
    .click();
  await owner.getByLabel("Daily runs", { exact: true }).fill("0");
  await owner.getByRole("button", { name: "Save limits", exact: true }).click();
  await expect(owner.getByRole("status")).toContainText("Saved");
  await owner.screenshot({
    path: "../.qa/workspace-usage.png",
    fullPage: true,
  });
  await owner.getByRole("button", { name: "Close dialog" }).click();
  await owner
    .getByRole("button", { name: "Execute agent", exact: true })
    .click();
  await owner
    .getByRole("button", { name: "Execute & trace", exact: true })
    .click();
  await expect(owner.getByRole("alert")).toContainText(
    "daily usage limit reached",
  );
  await owner.getByRole("button", { name: "Close dialog" }).click();
  await owner.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    owner.getByRole("button", { name: "Create your workspace", exact: true }),
  ).toBeVisible();
  await owner.screenshot({ path: "../.qa/public-demo.png", fullPage: true });
  await owner.setViewportSize({ width: 390, height: 844 });
  expect(
    await owner.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await owner.screenshot({
    path: "../.qa/public-demo-mobile.png",
    fullPage: true,
  });
  await ownerContext.close();
  await memberContext.close();
});
