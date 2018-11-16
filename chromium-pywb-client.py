import asyncio
import uvloop
from simplechrome import launch

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

async def main():
    browser = await launch()
    page = await browser.newPage()
    page.setDefaultNavigationTimeout(1000)
    await page.goto('http://localhost:8080/hello-mars/record/http://localhost:8000/')
    # await browser.close()

asyncio.get_event_loop().run_until_complete(main())
