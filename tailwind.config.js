/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './frontend/src/**/*.{js,ts,jsx,tsx}'],
  theme: { extend: { colors: { forge: { navy: '#142135', cobalt: '#2563eb' } } } },
  plugins: [],
};
