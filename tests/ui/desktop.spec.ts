import { expect, test } from "../../web/node_modules/@playwright/test";

for (const theme of ["dark", "light"]) {
  for (const width of [1440, 390]) {
    test(`${theme} desktop layout at ${width}px`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript(
        ({ theme }) => {
          const endpoint = "http://127.0.0.1:8181";
          localStorage.setItem("nicotine-endpoint", endpoint);
          localStorage.setItem(
            "nicotine-layout",
            JSON.stringify({
              state: { theme, density: "compact", tabs: [] },
              version: 0,
            }),
          );
          sessionStorage.setItem(
            "nicotine-session",
            JSON.stringify({
              endpoint,
              session_token: "ui-test",
              csrf: "ui-test",
              expires: Date.now() / 1000 + 3600,
            }),
          );
        },
        { theme },
      );
      await page.route("**/api/v1/**", async (route) => {
        const path = new URL(route.request().url()).pathname.replace(
          "/api/v1",
          "",
        );
        if (path === "/events") {
          await route.fulfill({
            contentType: "text/event-stream",
            body: ": heartbeat\n\n",
          });
          return;
        }
        const responses: Record<string, unknown> = {
          "/session": {
            csrf: "ui-test",
            version: "0.2.0",
            nicotine_version: "3.3.6",
          },
          "/status": {
            connected: true,
            username: "listener",
            away: false,
            download_speed: 1048576,
            upload_speed: 262144,
          },
          "/searches": [{ token: 1, term: "Ambient works", mode: "global" }],
          "/searches/1": {
            items: Array.from({ length: 60 }, (_, i) => ({
              id: String(i),
              username: "musiclover",
              virtual_path: `Music/Ambient/Track ${i + 1}.flac`,
              size: 24576000,
              speed: 1048576,
              bitrate: 900,
            })),
            truncated: false,
          },
          "/downloads": [],
          "/transfers/limits": {},
        };
        await route.fulfill({
          json: { ok: true, data: responses[path] ?? {}, cursor: "test:1" },
        });
      });
      await page.goto("/search/1");
      const nav = page.getByRole("navigation", { name: "Main sections" });
      await expect(
        nav.getByRole("link", { name: "Search", exact: true }),
      ).toHaveAttribute("aria-current", "page");
      await expect(
        page.getByRole("cell", {
          name: "Music/Ambient/Track 1.flac",
          exact: true,
        }),
      ).toBeVisible();
      await expect(
        page.getByRole("contentinfo").getByText("listener"),
      ).toBeVisible();
      const row = page.locator("tbody tr").first();
      expect((await row.boundingBox())?.height).toBe(28);
      await row.getByRole("checkbox").check();
      await expect(row).toHaveAttribute("aria-selected", "true");
      // Both themes must keep normal text readable on their actual surfaces.
      const contrast = await page.evaluate(() => {
        function luminance(color: string) {
          const rgb = color
            .match(/[\d.]+/g)!
            .slice(0, 3)
            .map(Number)
            .map((c) => {
              const channel = c / 255;
              return channel <= 0.04045
                ? channel / 12.92
                : ((channel + 0.055) / 1.055) ** 2.4;
            });
          return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
        }
        return [
          ".data-viewport",
          "thead",
          "tr[aria-selected='true']",
          ".search-form .primary",
        ].map((selector) => {
          const style = getComputedStyle(document.querySelector(selector)!);
          const a = luminance(style.color);
          const b = luminance(style.backgroundColor);
          return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
        });
      });
      for (const ratio of contrast) expect(ratio).toBeGreaterThanOrEqual(4.5);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      if (width > 760) {
        const main = await page.locator("main").boundingBox();
        const footer = await page.getByRole("contentinfo").boundingBox();
        expect(main!.y + main!.height).toBeLessThanOrEqual(footer!.y);
      }
      await page.screenshot({
        path: testInfo.outputPath("search.png"),
        fullPage: true,
      });
      await page.keyboard.press("Control+k");
      await expect(page.getByRole("dialog")).toBeVisible();
      await page.screenshot({
        path: testInfo.outputPath("navigation-dialog.png"),
        fullPage: true,
      });
      await page.keyboard.press("Escape");
      await nav.getByRole("link", { name: "Downloads", exact: true }).click();
      await expect(
        page.getByRole("heading", { name: "Downloads", exact: true }),
      ).toBeVisible();
    });
  }
}
