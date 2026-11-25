// The seeded data (api/seed_data.py) covers 26 Nov - 1 Dec 2026; 27 Nov is the scripted demo day.
export const DEMO_DATE = '2026-11-27'
export const SEED_DATES = ['2026-11-26', '2026-11-27', '2026-11-28', '2026-11-29', '2026-11-30', '2026-12-01']

export const POPULAR_ROUTES = [
  { origin: 'SBC', dest: 'HYB', label: 'Bengaluru → Hyderabad', hint: 'festive rush' },
  { origin: 'SBC', dest: 'JP', label: 'Bengaluru → Jaipur', hint: 'with changes' },
  { origin: 'NDLS', dest: 'KOTA', label: 'Delhi → Kota' },
  { origin: 'MMCT', dest: 'PUNE', label: 'Mumbai → Pune' },
]

// Clicking one sends the text to Sarvam's extraction (no microphone needed).
export const EXAMPLE_PHRASES = [
  'Mujhe 27 November ko Bangalore se Hyderabad jaana hai. Train nahi mili toh shared cab dekhna.',
  'Kal Delhi se Kota jaana hai',
  'I want to go from Pune to Mumbai on 30 November',
]
