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
