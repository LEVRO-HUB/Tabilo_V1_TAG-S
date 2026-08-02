import { Fragment, useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { createSubstitution, getSubstitutionSuggestions, getTodaysSchedule } from '../api/client'

const MANAGEMENT_ROLES = ['ADMIN', 'COORDINATOR']

function today() {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function formatTime(value) {
  return value?.slice(0, 5) ?? ''
}

export default function TodaysSchedulePage() {
  const { token, user } = useAuth()
  const canManage = MANAGEMENT_ROLES.includes(user?.role)

  const [date, setDate] = useState(today)
  const [schedule, setSchedule] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)

  const [openCellId, setOpenCellId] = useState(null)
  const [suggestions, setSuggestions] = useState([])
  const [suggestionsLoading, setSuggestionsLoading] = useState(false)
  const [suggestionsError, setSuggestionsError] = useState('')
  const [selectedTeacherId, setSelectedTeacherId] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState('')

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setLoadError('')
      try {
        const data = await getTodaysSchedule(token, date)
        if (!cancelled) setSchedule(data)
      } catch (err) {
        if (!cancelled) setLoadError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [token, date, refreshKey])

  // Changing the date abandons whatever substitute-picking panel was open.
  useEffect(() => {
    closePanel()
  }, [date])

  function closePanel() {
    setOpenCellId(null)
    setSuggestions([])
    setSuggestionsError('')
    setSelectedTeacherId('')
    setConfirmError('')
  }

  async function openPanel(cellId) {
    if (openCellId === cellId) {
      closePanel()
      return
    }
    setOpenCellId(cellId)
    setSuggestions([])
    setSuggestionsError('')
    setSelectedTeacherId('')
    setConfirmError('')
    setSuggestionsLoading(true)
    try {
      const data = await getSubstitutionSuggestions(token, cellId, date)
      setSuggestions(data.candidates)
    } catch (err) {
      setSuggestionsError(err.message)
    } finally {
      setSuggestionsLoading(false)
    }
  }

  async function handleConfirm(cellId) {
    if (!selectedTeacherId) return
    setConfirming(true)
    setConfirmError('')
    try {
      await createSubstitution(token, cellId, date, Number(selectedTeacherId))
      closePanel()
      setRefreshKey((key) => key + 1)
    } catch (err) {
      setConfirmError(err.message)
    } finally {
      setConfirming(false)
    }
  }

  const columnCount = canManage ? 5 : 4

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900">Today's Schedule</h1>
        <div>
          <label htmlFor="schedule-date" className="mb-1 block text-xs font-medium text-gray-500">Date</label>
          <input
            id="schedule-date"
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
        </div>
      </div>

      {loading && <p className="text-gray-500">Loading…</p>}
      {loadError && !loading && <p className="text-red-600">{loadError}</p>}

      {!loading && !loadError && schedule && !schedule.is_working_day && (
        <p className="text-gray-500">
          No classes scheduled -- {schedule.date} is not a working day ({schedule.reason}).
        </p>
      )}

      {!loading && !loadError && schedule && schedule.is_working_day && (
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Time</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Class</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Subject</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Teacher</th>
              {canManage && (
                <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
              )}
            </tr>
          </thead>
          <tbody>
            {schedule.cells.map((cell) => (
              <Fragment key={cell.cell_id}>
                <tr>
                  <td className="border border-gray-200 px-3 py-2 text-gray-500">
                    P{cell.time_slot.period_number} · {formatTime(cell.time_slot.start_time)}–{formatTime(cell.time_slot.end_time)}
                  </td>
                  <td className="border border-gray-200 px-3 py-2">{cell.class_division}</td>
                  <td className="border border-gray-200 px-3 py-2">{cell.subject}</td>
                  <td className="border border-gray-200 px-3 py-2">
                    <div>{cell.teacher}</div>
                    {cell.substitution && (
                      <div className="text-xs text-blue-700">Substitute: {cell.substitution.substitute_teacher_name}</div>
                    )}
                  </td>
                  {canManage && (
                    <td className="border border-gray-200 px-3 py-2">
                      <button
                        type="button"
                        onClick={() => openPanel(cell.cell_id)}
                        className="text-purple-600 hover:underline"
                      >
                        {cell.substitution ? 'Change substitute' : 'Find substitute'}
                      </button>
                    </td>
                  )}
                </tr>
                {openCellId === cell.cell_id && (
                  <tr>
                    <td colSpan={columnCount} className="border border-gray-200 bg-gray-50 px-3 py-3">
                      {suggestionsLoading && <p className="text-gray-500">Finding available substitutes…</p>}
                      {suggestionsError && (
                        <p role="alert" className="text-red-600">{suggestionsError}</p>
                      )}
                      {!suggestionsLoading && !suggestionsError && suggestions.length === 0 && (
                        <p className="text-gray-500">No eligible substitute is available for this slot.</p>
                      )}
                      {!suggestionsLoading && !suggestionsError && suggestions.length > 0 && (
                        <div className="space-y-2">
                          <ul className="space-y-1">
                            {suggestions.map((candidate) => (
                              <li key={candidate.teacher_id} className="flex items-center gap-2">
                                <input
                                  type="radio"
                                  id={`candidate-${cell.cell_id}-${candidate.teacher_id}`}
                                  name={`candidate-${cell.cell_id}`}
                                  value={candidate.teacher_id}
                                  checked={selectedTeacherId === String(candidate.teacher_id)}
                                  onChange={(event) => setSelectedTeacherId(event.target.value)}
                                />
                                <label htmlFor={`candidate-${cell.cell_id}-${candidate.teacher_id}`} className="text-sm">
                                  <span className="font-medium text-gray-900">{candidate.teacher_name}</span>
                                  <span className="text-gray-500"> — {candidate.reason} ({candidate.periods_today} period{candidate.periods_today === 1 ? '' : 's'} today)</span>
                                </label>
                              </li>
                            ))}
                          </ul>
                          {confirmError && (
                            <p role="alert" className="text-sm text-red-600">{confirmError}</p>
                          )}
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => handleConfirm(cell.cell_id)}
                              disabled={!selectedTeacherId || confirming}
                              className="rounded-md bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {confirming ? 'Confirming…' : 'Confirm substitute'}
                            </button>
                            <button
                              type="button"
                              onClick={closePanel}
                              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {schedule.cells.length === 0 && (
              <tr>
                <td colSpan={columnCount} className="border border-gray-200 px-3 py-4 text-center text-gray-500">
                  No classes scheduled for this date.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
