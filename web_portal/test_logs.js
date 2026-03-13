const puppeteer = require('puppeteer');
(async () => {
    const browser = await puppeteer.launch({headless: "new"});
    const page = await browser.newPage();
    page.on('console', msg => console.log('PAGE LOG:', msg.text()));
    page.on('pageerror', err => console.log('PAGE ERROR:', err.toString()));
    
    await page.goto('http://localhost:8000');
    await page.type('#portal-password', 'DeerCamp');
    await page.click('#auth-form button');
    await page.waitForTimeout(3000);
    await browser.close();
})();
