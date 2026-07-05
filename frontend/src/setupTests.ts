import '@testing-library/jest-dom';

// ── jsdom polyfills for missing browser APIs ──────────────────────────────────

// react-hot-toast uses window.matchMedia for prefers-color-scheme detection
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// react-markdown uses scrollIntoView
window.HTMLElement.prototype.scrollIntoView = () => {};
