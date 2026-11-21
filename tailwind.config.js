/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './public/**/*.html',
    './public/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        'perto-ink': '#10243e',
        'perto-sea': '#1f6f8b',
        'perto-sun': '#ffc233',
        'perto-bg': '#f1f5f7',
        'perto-road': '#dce5ea',
        'perto-ok': '#1a8f5a',
        'perto-card': '#ffffff',
      },
      fontFamily: {
        headline: ['Plus Jakarta Sans', 'sans-serif'],
        body: ['Inter', 'sans-serif'],
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/container-queries'),
  ],
};
