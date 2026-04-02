/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:        '#0a0e1a',
        card:      '#1a1f35',
        border:    '#2a3050',
        accent:    '#2196f3',
        success:   '#00d4aa',
        danger:    '#ef4444',
        warning:   '#f59e0b',
        muted:     '#6b7280',
        'text-primary':   '#e2e8f0',
        'text-secondary': '#94a3b8',
        'text-muted':     '#4b5563',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
}
