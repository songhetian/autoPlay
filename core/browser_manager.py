import os
import sys
import threading
import time

from playwright.sync_api import sync_playwright


class BrowserManager:
    def __init__(self):
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None
        self.is_picking = False
        self.pick_result = None
        self._lock = threading.Lock()

    def start(self, url="about:blank", user_data_dir=None):
        self._configure_browser_runtime_path()
        if not self.pw:
            self.pw = sync_playwright().start()
        if not self.browser:
            if user_data_dir:
                os.makedirs(user_data_dir, exist_ok=True)
                self.context = self.pw.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=False,
                )
                self.browser = self.context.browser
                self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            else:
                self.browser = self.pw.chromium.launch(headless=False)
                self.context = self.browser.new_context()
                self.page = self.context.new_page()
        self.page.goto(url)
        return self.page

    def _configure_browser_runtime_path(self):
        candidate_paths = []
        if getattr(sys, "frozen", False):
            app_dir = os.path.dirname(sys.executable)
            candidate_paths.append(os.path.join(app_dir, "ms-playwright"))
            candidate_paths.append(os.path.join(app_dir, "_internal", "ms-playwright"))
        else:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            candidate_paths.append(os.path.join(base_dir, "ms-playwright"))

        for path in candidate_paths:
            if os.path.isdir(path):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = path
                return

    def stop(self):
        if self.context:
            self.context.close()
        elif self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()
        self.pw = None
        self.browser = None
        self.context = None
        self.page = None
        self.is_picking = False

    def enable_picker(self):
        if not self.page:
            raise RuntimeError("browser not started")

        self.is_picking = True
        self.pick_result = None
        self.page.expose_function("py_element_picked", self._on_element_picked)
        self.page.evaluate(
            """
            (() => {
              if (window.__rpaPickerInstalled) return;
              window.__rpaPickerInstalled = true;

              const style = document.createElement('style');
              style.id = 'rpa-picker-style';
              style.textContent = `
                .rpa-picker-hover {
                  outline: 2px solid #2563eb !important;
                  background: rgba(37, 99, 235, 0.10) !important;
                  cursor: crosshair !important;
                }
              `;
              document.head.appendChild(style);

              let lastEl = null;

              function buildCss(el) {
                if (!(el instanceof Element)) return '';
                if (el.id) return `#${CSS.escape(el.id)}`;
                const parts = [];
                while (el && el.nodeType === 1 && el !== document.body) {
                  let part = el.nodeName.toLowerCase();
                  if (el.classList.length) {
                    const cls = Array.from(el.classList).slice(0, 2).map(c => `.${CSS.escape(c)}`).join('');
                    if (cls) part += cls;
                  }
                  const siblings = el.parentNode ? Array.from(el.parentNode.children).filter(n => n.nodeName === el.nodeName) : [];
                  if (siblings.length > 1) {
                    const index = siblings.indexOf(el) + 1;
                    part += `:nth-of-type(${index})`;
                  }
                  parts.unshift(part);
                  el = el.parentElement;
                }
                return parts.join(' > ');
              }

              function buildXpath(el) {
                if (!(el instanceof Element)) return '';
                if (el.id) return `//*[@id="${el.id}"]`;
                const parts = [];
                while (el && el.nodeType === 1) {
                  let index = 1;
                  let sibling = el.previousElementSibling;
                  while (sibling) {
                    if (sibling.nodeName === el.nodeName) index += 1;
                    sibling = sibling.previousElementSibling;
                  }
                  parts.unshift(`${el.nodeName.toLowerCase()}[${index}]`);
                  el = el.parentElement;
                }
                return '/' + parts.join('/');
              }

              function bestText(el) {
                const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
                return text.slice(0, 40);
              }

              document.addEventListener('mouseover', (event) => {
                if (lastEl) lastEl.classList.remove('rpa-picker-hover');
                event.target.classList.add('rpa-picker-hover');
                lastEl = event.target;
              }, true);

              document.addEventListener('click', (event) => {
                if (!window.__rpaPickerInstalled) return;
                event.preventDefault();
                event.stopPropagation();
                const el = event.target;
                window.py_element_picked({
                  tag: el.tagName.toLowerCase(),
                  text: bestText(el),
                  css: buildCss(el),
                  xpath: buildXpath(el),
                });
              }, true);
            })();
            """
        )

    def wait_for_pick(self, timeout=300):
        start = time.time()
        while self.is_picking and time.time() - start < timeout:
            time.sleep(0.2)
        return self.pick_result

    def locator(self, locator_type, locator_value):
        if not self.page:
            raise RuntimeError("browser not started")
        if locator_type == "XPath":
            return self.page.locator(f"xpath={locator_value}")
        if locator_type == "文本匹配":
            return self.page.get_by_text(locator_value)
        if locator_type == "ID":
            return self.page.locator(f"#{locator_value}")
        if locator_type == "Name":
            return self.page.locator(f"[name='{locator_value}']")
        return self.page.locator(locator_value)

    def test_locator(self, url, locator_type, locator_value, user_data_dir=None, timeout=10000):
        self.start(url, user_data_dir=user_data_dir)
        target = self.locator(locator_type, locator_value)
        target.first.wait_for(state="visible", timeout=timeout)
        target.first.scroll_into_view_if_needed(timeout=timeout)
        target.first.highlight()
        return True

    def click(self, locator_type, locator_value, click_count=1):
        self.locator(locator_type, locator_value).first.click(click_count=click_count)

    def focus(self, locator_type, locator_value):
        self.locator(locator_type, locator_value).first.focus()

    def fill(self, locator_type, locator_value, text):
        target = self.locator(locator_type, locator_value).first
        target.click()
        target.fill(str(text))

    def wait_for(self, locator_type, locator_value, timeout=10000):
        self.locator(locator_type, locator_value).first.wait_for(state="visible", timeout=timeout)

    def refresh(self):
        self.page.reload()

    def press_key(self, key):
        self.page.keyboard.press(key)

    def screenshot(self, path):
        self.page.screenshot(path=path, full_page=True)

    def _on_element_picked(self, payload):
        with self._lock:
            self.pick_result = payload
            self.is_picking = False
