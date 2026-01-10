const baseConfig = require('../../tailwind.config.js');

/** @type {import('tailwindcss').Config} */
module.exports = {
  ...baseConfig,
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
    '../../packages/**/*.{js,ts,jsx,tsx}',
  ],
};
