"""Convert presentation.html to a multi-page PDF (one slide per page).

Navigates each slide via the presentation's goTo() function and
takes viewport screenshots at 2x resolution.
"""

import asyncio
import io
import sys
from pathlib import Path

from playwright.async_api import async_playwright

TOTAL_SLIDES = 19
VIEWPORT = {"width": 1920, "height": 1080}


async def main() -> None:
    html_path = Path(__file__).resolve().parent.parent / "docs" / "presentation.html"
    out_path = Path(__file__).resolve().parent.parent / "docs" / "presentation.pdf"

    if not html_path.exists():
        print(f"Not found: {html_path}", file=sys.stderr)
        sys.exit(1)

    file_url = html_path.as_uri()

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport=VIEWPORT,
            device_scale_factor=2,
        )
        await page.goto(file_url, wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # Hide nav UI once
        await page.evaluate(
            """() => {
                const counter = document.getElementById('counter');
                const nav = document.getElementById('slideNav');
                if (counter) counter.style.display = 'none';
                if (nav) nav.style.display = 'none';
            }"""
        )

        screenshots: list[bytes] = []

        for i in range(TOTAL_SLIDES):
            # Use the presentation's own goTo() which handles
            # active class, scroll, and chart initialization
            await page.evaluate(f"goTo({i})")
            # Generous wait for charts to animate and render
            await page.wait_for_timeout(1200)

            png = await page.screenshot(type="png", full_page=False)
            screenshots.append(png)
            print(f"  Captured slide {i + 1}/{TOTAL_SLIDES}")

        await browser.close()

    from PIL import Image

    images: list[Image.Image] = []
    for png in screenshots:
        img = Image.open(io.BytesIO(png)).convert("RGB")
        images.append(img)

    first, *rest = images
    first.save(
        out_path,
        save_all=True,
        append_images=rest,
        resolution=300,
    )

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\nPDF saved: {out_path} ({size_mb:.1f} MB)")
    print(f"Pages: {len(images)}")


if __name__ == "__main__":
    asyncio.run(main())
