import asyncio
import os
from datetime import datetime
import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

URL_PAGE = "https://mano.affidea.lt/services/2/65/?cityId=138236&serviceId=140499&visitPaymentTypeId=2"

TELEGRAM_BOT_TOKEN = "8278825958:AAEkK-8AIcorVhKYilU34LVwWRFFy_lOR9Q"
TELEGRAM_CHAT_ID = "6312004108"
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


async def extract_santariskes_date(page):
    """Randa Santariškių kortelę, grąžina datą po 'Nuo:' ir ar mygtukas aktyvus."""
    cards = await page.query_selector_all("div:has(button:has-text('Registruotis'))")

    for card in cards:
        text = (await card.inner_text()).strip()

        if "Santariški" not in text:
            continue  # ignoruojam Antakalnio ir kitas vietas

        lines = [line.strip() for line in text.split("\n") if line.strip()]
        nuo = next((l for l in lines if l.startswith("Nuo:")), "Nuo: nėra datos")

        # Tikrinam mygtuko būklę
        btn = await card.query_selector("button:has-text('Registruotis')")
        disabled = await btn.is_disabled() if btn else True

        return nuo, not disabled  # grąžina datą ir aktyvumo būseną

    # jei nerado Santariškių kortelės
    return "Nuo: nerasta", False


async def check_page_santariskes():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(URL_PAGE, wait_until="load", timeout=60000)
        except PlaywrightTimeoutError:
            print("[WARN] Page.goto timeout, bandau naudoti tai, kas spėjo užsikrauti")

        await page.wait_for_timeout(4000)

        nuo_text, active = await extract_santariskes_date(page)
        await browser.close()

    return nuo_text, active


async def main():
    print(f"[INFO] Tikrinu {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ...")

    nuo_text, active = await check_page_santariskes()
    prev_state = read_state()
    current_state = "active" if active else "inactive"

    print(f"[DEBUG] Santariškių būsena: {current_state}, {nuo_text}")

    if current_state != prev_state:
        if current_state == "active":
            send_telegram_message(
                f"🟢 AFFIDEA: yra laisvų vietų Santariškėse!\n{nuo_text}\n\n👉 {URL_PAGE}"
            )
        elif prev_state not in ("unknown", ""):
            send_telegram_message(
                "🔴 AFFIDEA: Santariškių vietos vėl dingo."
            )
        write_state(current_state)

    print(f"[INFO] Būsena: {current_state}")


if __name__ == "__main__":
    asyncio.run(main())
