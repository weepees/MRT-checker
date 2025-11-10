import asyncio
import os
from datetime import datetime

import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

URL_PAGE = "https://mano.affidea.lt/services/2/65/?cityId=138236&serviceId=140499&visitPaymentTypeId=2"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "fallback")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "fallback")

STATE_FILE = "state.txt"


def read_state() -> str:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "unknown"


def write_state(state: str):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(state)


def send_telegram_message(text: str):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        requests.get(api_url, params=params, timeout=10)
    except Exception as e:
        print(f"[ERROR] Nepavyko išsiųsti Telegram žinutės: {e}")


async def check_page_has_active_button() -> bool:
    async with async_playwright() as p:
        # DABAR: headless=False, kad matytum langą. Kai veiks – pakeisim į True.
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            # laukiam tik "load", ne "networkidle"
            await page.goto(URL_PAGE, wait_until="load", timeout=60000)
        except PlaywrightTimeoutError:
            print("[WARN] Page.goto timeout, bandau naudoti tai, kas spėjo užsikrauti")

        # duodam dar 3 s JS’ui susidėliot viską
        await page.wait_for_timeout(3000)

        # visi mygtukai su tekstu "Registruotis"
        buttons = await page.query_selector_all('button:has-text("Registruotis")')
        print(f"[DEBUG] Rasta 'Registruotis' mygtukų: {len(buttons)}")

        has_active = False
        for btn in buttons:
            disabled = await btn.is_disabled()
            print(f"[DEBUG] Mygtukas disabled={disabled}")
            if not disabled:
                has_active = True
                break

        await browser.close()

    return has_active


async def main():
    print(f"[INFO] Tikrinu {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ...")

    has_active = await check_page_has_active_button()
    prev_state = read_state()
    current_state = "active" if has_active else "inactive"

    print(f"[DEBUG] Ankstesnė būsena: {prev_state}, dabartinė: {current_state}")

    if current_state != prev_state:
        if current_state == "active":
            send_telegram_message(
                f"🟢 AFFIDEA: atsirado bent vienas aktyvus REGISTRUOTIS mygtukas!\n{URL_PAGE}"
            )
        elif prev_state not in ("unknown", ""):
            send_telegram_message(
                "🔴 AFFIDEA: nebeliko aktyvių REGISTRUOTIS mygtukų (viskas vėl užimta)."
            )
        write_state(current_state)

    print(f"[INFO] Būsena: {current_state}")


if __name__ == "__main__":
    asyncio.run(main())
