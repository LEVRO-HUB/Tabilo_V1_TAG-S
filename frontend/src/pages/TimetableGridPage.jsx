import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { getClassDivisions, getSolverRun, getTerms, getTimetableGrid, triggerSolverRun } from '../api/client'
import { dayLabel, pivotSlotsToGrid } from '../utils/timetableGrid'

const POLL_INTERVAL_MS = 2000

export default function TimetableGridPage() {
  const { token } = useAuth()

  const [terms, setTerms] = useState([])
  const [classDivisions, setClassDivisions] = useState([])
  const [selectedTermId, setSelectedTermId] = useState('')
  const [selectedClassDivisionId, setSelectedClassDivisionId] = useState('')
  const [loadingOptions, setLoadingOptions] = useState(true)
  const [optionsError, setOptionsError] = useState('')

  const [grid, setGrid] = useState(null)
  const [loadingGrid, setLoadingGrid] = useState(false)
  const [gridError, setGridError] = useState('')
  const [gridRefreshKey, setGridRefreshKey] = useState(0)

  const [solverRunId, setSolverRunId] = useState(null)
  const [solverStatus, setSolverStatus] = useState(null)
  const [solverError, setSolverError] = useState('')
  const isGenerating = solverStatus === 'PENDING' || solverStatus === 'RUNNING'

  // Load terms + class divisions once, then auto-select the active term
  // (falling back to the first) and the first class division -- no
  // separate "click to load" step.
  useEffect(() => {
    let cancelled = false

    async function loadOptions() {
      setLoadingOptions(true)
      setOptionsError('')
      try {
        const [termsData, classDivisionsData] = await Promise.all([
          getTerms(token),
          getClassDivisions(token),
        ])
        if (cancelled) return

        setTerms(termsData)
        setClassDivisions(classDivisionsData)

        const defaultTerm = termsData.find((term) => term.is_active) ?? termsData[0]
        if (defaultTerm) setSelectedTermId(String(defaultTerm.id))
        if (classDivisionsData[0]) setSelectedClassDivisionId(String(classDivisionsData[0].id))
      } catch (err) {
        if (!cancelled) setOptionsError(err.message)
      } finally {
        if (!cancelled) setLoadingOptions(false)
      }
    }

    loadOptions()
    return () => {
      cancelled = true
    }
  }, [token])

  // Re-fetch the grid whenever the selected term or class division changes
  // (including the initial auto-selected values), or when gridRefreshKey
  // is bumped after a successful "Generate Timetable" run.
  useEffect(() => {
    if (!selectedTermId || !selectedClassDivisionId) return
    let cancelled = false

    async function loadGrid() {
      setLoadingGrid(true)
      setGridError('')
      try {
        const data = await getTimetableGrid(token, selectedTermId, selectedClassDivisionId)
        if (!cancelled) setGrid(data)
      } catch (err) {
        if (!cancelled) {
          setGrid(null)
          setGridError(err.message)
        }
      } finally {
        if (!cancelled) setLoadingGrid(false)
      }
    }

    loadGrid()
    return () => {
      cancelled = true
    }
  }, [token, selectedTermId, selectedClassDivisionId, gridRefreshKey])

  // Changing which term/class division is selected abandons any in-flight
  // solver run tracking -- the polling effect below cleans up its own
  // timeout as soon as solverRunId changes.
  useEffect(() => {
    setSolverRunId(null)
    setSolverStatus(null)
    setSolverError('')
  }, [selectedTermId, selectedClassDivisionId])

  // Poll GET /api/solver-runs/<id>/ every ~2s until SUCCESS or FAILED.
  // Recursive setTimeout (not setInterval) so a poll never overlaps the
  // next one, and cleanup only has one timer to worry about.
  useEffect(() => {
    if (!solverRunId) return
    let cancelled = false
    let timeoutId = null

    async function poll() {
      try {
        const run = await getSolverRun(token, solverRunId)
        if (cancelled) return
        setSolverStatus(run.status)

        if (run.status === 'SUCCESS') {
          setGridRefreshKey((key) => key + 1)
          return
        }
        if (run.status === 'FAILED') {
          setSolverError(run.error_message || 'The solver failed for an unknown reason.')
          return
        }
        timeoutId = setTimeout(poll, POLL_INTERVAL_MS)
      } catch (err) {
        if (!cancelled) {
          setSolverStatus('FAILED')
          setSolverError(err.message)
        }
      }
    }

    poll()

    return () => {
      cancelled = true
      if (timeoutId) clearTimeout(timeoutId)
    }
  }, [token, solverRunId])

  async function handleGenerate() {
    setSolverError('')
    setSolverStatus('PENDING')
    try {
      const run = await triggerSolverRun(token, selectedTermId)
      setSolverRunId(run.id)
      setSolverStatus(run.status)
    } catch (err) {
      setSolverStatus('FAILED')
      setSolverError(err.message)
    }
  }

  if (loadingOptions) {
    return <p className="text-gray-500">Loading…</p>
  }

  if (optionsError) {
    return <p className="text-red-600">{optionsError}</p>
  }

  if (terms.length === 0 || classDivisions.length === 0) {
    return <p className="text-gray-500">No terms or class divisions found for your institution yet.</p>
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="term-select" className="mb-1 block text-xs font-medium text-gray-500">
            Term
          </label>
          <select
            id="term-select"
            value={selectedTermId}
            onChange={(event) => setSelectedTermId(event.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
          >
            {terms.map((term) => (
              <option key={term.id} value={term.id}>
                {term.name}
                {term.is_active ? ' (active)' : ''}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="class-division-select" className="mb-1 block text-xs font-medium text-gray-500">
            Class
          </label>
          <select
            id="class-division-select"
            value={selectedClassDivisionId}
            onChange={(event) => setSelectedClassDivisionId(event.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
          >
            {classDivisions.map((division) => (
              <option key={division.id} value={division.id}>
                {division.name} - {division.section}
              </option>
            ))}
          </select>
        </div>

        <button
          type="button"
          onClick={handleGenerate}
          disabled={!selectedTermId || isGenerating}
          className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isGenerating ? 'Generating…' : 'Generate Timetable'}
        </button>

        {isGenerating && (
          <p className="text-sm text-gray-500" role="status">
            Generating timetable… this can take up to 30 seconds.
          </p>
        )}
      </div>

      {solverError && (
        <p role="alert" className="mb-4 text-sm text-red-600">
          {solverError}
        </p>
      )}

      {loadingGrid && <p className="text-gray-500">Loading timetable…</p>}
      {gridError && !loadingGrid && <p className="text-red-600">{gridError}</p>}
      {!loadingGrid && !gridError && grid && <GridTable grid={grid} />}
    </div>
  )
}

function GridTable({ grid }) {
  const { dayIdentifiers, periodNumbers, slotByDayAndPeriod } = pivotSlotsToGrid(grid.slots)
  const institutionType = grid.institution.institution_type

  return (
    <div className="mt-4 overflow-x-auto">
      <table className="min-w-full border-collapse text-sm">
        <thead>
          <tr>
            <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">
              Period
            </th>
            {dayIdentifiers.map((dayIdentifier) => (
              <th
                key={dayIdentifier}
                className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500"
              >
                {dayLabel(institutionType, dayIdentifier)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {periodNumbers.map((periodNumber) => (
            <tr key={periodNumber}>
              <td className="border border-gray-200 px-3 py-2 font-medium text-gray-500">{periodNumber}</td>
              {dayIdentifiers.map((dayIdentifier) => (
                <td key={dayIdentifier} className="border border-gray-200 px-3 py-2 align-top">
                  <SlotCell slot={slotByDayAndPeriod.get(`${dayIdentifier}-${periodNumber}`)} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SlotCell({ slot }) {
  if (!slot) return null

  if (slot.is_break) {
    return <span className="text-xs italic text-gray-400">Break</span>
  }

  if (!slot.cell) {
    return <span className="text-xs italic text-gray-400">Free period</span>
  }

  return (
    <div>
      <div className="flex items-center gap-1">
        <p className="font-medium text-gray-900">{slot.cell.subject}</p>
        {slot.cell.is_locked && (
          <span title="Locked" aria-label="Locked" className="text-xs text-gray-400">
            🔒
          </span>
        )}
      </div>
      <p className="text-xs text-gray-500">{slot.cell.teacher}</p>
    </div>
  )
}
