import subprocess
import time
from playwright.sync_api import sync_playwright

def main():
    print("Starting flask...")
    p = subprocess.Popen(["python", "app.py"])
    time.sleep(3) # wait for boot
    
    print("Capturing screenshot...")
    try:
        with sync_playwright() as p_wt:
            browser = p_wt.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("http://localhost:5000")
            page.screenshot(path="screenshot.png", full_page=True)
            browser.close()
    except Exception as e:
        print("Playwright error:", e)
        
    p.terminate()
    print("Done")

if __name__ == '__main__':
    main()
