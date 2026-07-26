// Tabilo — pure helpers for turning the flat `slots` array from
// GET /api/timetable-grid/ into a day x period table. Kept separate from
// the page component so the day-labeling rule is easy to find and adjust.

const SCHOOL_DAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

export function dayLabel(institutionType, dayIdentifier) {
  if (institutionType === 'SCHOOL') {
    return SCHOOL_DAY_LABELS[dayIdentifier - 1] ?? `Day ${dayIdentifier}`
  }
  return `Day ${dayIdentifier}`
}

// Returns { dayIdentifiers, periodNumbers, slotByDayAndPeriod } where
// dayIdentifiers/periodNumbers are the distinct, sorted axis values and
// slotByDayAndPeriod maps "day-period" -> slot for O(1) cell lookup.
export function pivotSlotsToGrid(slots) {
  const dayIdentifiers = [...new Set(slots.map((slot) => slot.day_identifier))].sort((a, b) => a - b)
  const periodNumbers = [...new Set(slots.map((slot) => slot.period_number))].sort((a, b) => a - b)

  const slotByDayAndPeriod = new Map()
  for (const slot of slots) {
    slotByDayAndPeriod.set(`${slot.day_identifier}-${slot.period_number}`, slot)
  }

  return { dayIdentifiers, periodNumbers, slotByDayAndPeriod }
}
