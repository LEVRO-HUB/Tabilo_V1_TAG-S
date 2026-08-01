import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { createTeacher, getTeachers, getTerms, triggerResignationRecovery, updateTeacher } from '../api/client'
import { useSolverRunPolling } from '../hooks/useSolverRunPolling'

const EMPTY_FORM = { name: '', email: '', max_periods_per_day: '', max_periods_per_week: '' }
const SUCCESS_MESSAGE_DURATION_MS = 4000

export default function TeachersPage() {
  const { token } = useAuth()

  const [teachers, setTeachers] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)

  // Recover Schedule always targets the institution's current active term
  // -- same "no separate picker" principle as TimetableGridPage's default
  // term selection. Known limitation: a teacher resigning mid-way through
  // multiple concurrently-open terms can only be recovered here one term
  // (the active one) at a time; recovering older/other terms still works
  // via `manage.py recover_resignation <teacher_id> <term_id>`.
  const [activeTerm, setActiveTerm] = useState(null)

  const [recoveringTeacherId, setRecoveringTeacherId] = useState(null)
  const [recoverySuccessTeacherId, setRecoverySuccessTeacherId] = useState(null)
  const {
    status: recoveryStatus,
    error: recoveryError,
    isPolling: isRecovering,
    trigger: triggerRecoveryPolling,
  } = useSolverRunPolling(token)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setLoadError('')
      try {
        const data = await getTeachers(token)
        if (!cancelled) setTeachers(data)
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
  }, [token, refreshKey])

  useEffect(() => {
    let cancelled = false
    async function loadActiveTerm() {
      try {
        const termsData = await getTerms(token)
        if (cancelled) return
        setActiveTerm(termsData.find((term) => term.is_active) ?? termsData[0] ?? null)
      } catch {
        // Recover Schedule just stays disabled (activeTerm null) -- the
        // rest of the page (list, add/edit, resign/reactivate) still works
        // fine without a term, so this isn't surfaced as a page-level error.
      }
    }
    loadActiveTerm()
    return () => {
      cancelled = true
    }
  }, [token])

  useEffect(() => {
    if (!recoverySuccessTeacherId) return
    const timeoutId = setTimeout(() => setRecoverySuccessTeacherId(null), SUCCESS_MESSAGE_DURATION_MS)
    return () => clearTimeout(timeoutId)
  }, [recoverySuccessTeacherId])

  function openCreateForm() {
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormError('')
    setShowForm(true)
  }

  function openEditForm(teacher) {
    setEditingId(teacher.id)
    setForm({
      name: teacher.name,
      email: teacher.email,
      max_periods_per_day: String(teacher.max_periods_per_day),
      max_periods_per_week: String(teacher.max_periods_per_week),
    })
    setFormError('')
    setShowForm(true)
  }

  function closeForm() {
    setShowForm(false)
    setEditingId(null)
    setForm(EMPTY_FORM)
    setFormError('')
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setFormError('')
    setSaving(true)
    const payload = {
      name: form.name,
      email: form.email,
      max_periods_per_day: Number(form.max_periods_per_day),
      max_periods_per_week: Number(form.max_periods_per_week),
    }
    try {
      if (editingId) {
        await updateTeacher(token, editingId, payload)
      } else {
        await createTeacher(token, payload)
      }
      closeForm()
      setRefreshKey((key) => key + 1)
    } catch (err) {
      setFormError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleToggleActive(teacher) {
    const confirmMessage = teacher.is_active
      ? `Mark ${teacher.name} as resigned? They will be greyed out but not deleted.`
      : `Reactivate ${teacher.name}?`
    if (!window.confirm(confirmMessage)) return
    try {
      await updateTeacher(token, teacher.id, { is_active: !teacher.is_active })
      setRefreshKey((key) => key + 1)
    } catch (err) {
      window.alert(err.message)
    }
  }

  function handleRecoverSchedule(teacher) {
    if (!activeTerm) return
    setRecoverySuccessTeacherId(null)
    setRecoveringTeacherId(teacher.id)
    triggerRecoveryPolling(() => triggerResignationRecovery(token, teacher.id, activeTerm.id), {
      onSuccess: () => setRecoverySuccessTeacherId(teacher.id),
    })
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900">Teachers</h1>
        {!showForm && (
          <button
            type="button"
            onClick={openCreateForm}
            className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
          >
            + Add Teacher
          </button>
        )}
      </div>

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="mb-6 space-y-4 rounded-lg border border-gray-200 bg-white p-4"
        >
          <h2 className="text-sm font-medium text-gray-900">{editingId ? 'Edit teacher' : 'New teacher'}</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="teacher-name" className="mb-1 block text-xs font-medium text-gray-500">Name</label>
              <input
                id="teacher-name"
                type="text"
                required
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="teacher-email" className="mb-1 block text-xs font-medium text-gray-500">Email</label>
              <input
                id="teacher-email"
                type="email"
                required
                value={form.email}
                onChange={(event) => setForm({ ...form, email: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="teacher-max-day" className="mb-1 block text-xs font-medium text-gray-500">
                Max periods / day
              </label>
              <input
                id="teacher-max-day"
                type="number"
                min="1"
                required
                value={form.max_periods_per_day}
                onChange={(event) => setForm({ ...form, max_periods_per_day: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="teacher-max-week" className="mb-1 block text-xs font-medium text-gray-500">
                Max periods / week
              </label>
              <input
                id="teacher-max-week"
                type="number"
                min="1"
                required
                value={form.max_periods_per_week}
                onChange={(event) => setForm({ ...form, max_periods_per_week: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
          </div>

          {formError && (
            <p role="alert" className="text-sm text-red-600">{formError}</p>
          )}

          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={saving}
              className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? 'Saving…' : editingId ? 'Save changes' : 'Create'}
            </button>
            <button
              type="button"
              onClick={closeForm}
              className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {loading && <p className="text-gray-500">Loading…</p>}
      {loadError && !loading && <p className="text-red-600">{loadError}</p>}

      {!loading && !loadError && (
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Name</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Email</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Max/Day</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Max/Week</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Status</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
            </tr>
          </thead>
          <tbody>
            {teachers.map((teacher) => (
              <tr key={teacher.id} className={teacher.is_active ? '' : 'bg-gray-50 text-gray-400'}>
                <td className="border border-gray-200 px-3 py-2">{teacher.name}</td>
                <td className="border border-gray-200 px-3 py-2">{teacher.email}</td>
                <td className="border border-gray-200 px-3 py-2">{teacher.max_periods_per_day}</td>
                <td className="border border-gray-200 px-3 py-2">{teacher.max_periods_per_week}</td>
                <td className="border border-gray-200 px-3 py-2">
                  {teacher.is_active ? (
                    <span className="text-green-700">Active</span>
                  ) : (
                    <span className="italic text-gray-400">Resigned</span>
                  )}
                </td>
                <td className="border border-gray-200 px-3 py-2">
                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      onClick={() => openEditForm(teacher)}
                      className="text-purple-600 hover:underline"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => handleToggleActive(teacher)}
                      disabled={!teacher.is_active && recoveringTeacherId === teacher.id && isRecovering}
                      className={
                        teacher.is_active
                          ? 'text-red-600 hover:underline'
                          : 'text-green-700 hover:underline disabled:cursor-not-allowed disabled:opacity-50'
                      }
                    >
                      {teacher.is_active ? 'Mark as resigned' : 'Reactivate'}
                    </button>
                    {!teacher.is_active && (
                      <button
                        type="button"
                        onClick={() => handleRecoverSchedule(teacher)}
                        disabled={!activeTerm || isRecovering}
                        className="text-blue-600 hover:underline disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {recoveringTeacherId === teacher.id && isRecovering ? 'Recovering…' : 'Recover Schedule'}
                      </button>
                    )}
                  </div>
                  {recoveringTeacherId === teacher.id && isRecovering && (
                    <p className="mt-1 text-xs text-gray-500" role="status">
                      Recovering schedule for {activeTerm?.name}…
                    </p>
                  )}
                  {recoveringTeacherId === teacher.id && recoveryStatus === 'SUCCESS' && recoverySuccessTeacherId === teacher.id && (
                    <p className="mt-1 text-xs text-green-700">Schedule recovered successfully.</p>
                  )}
                  {recoveringTeacherId === teacher.id && recoveryStatus === 'FAILED' && (
                    <p className="mt-1 text-xs text-red-600" role="alert">{recoveryError}</p>
                  )}
                </td>
              </tr>
            ))}
            {teachers.length === 0 && (
              <tr>
                <td colSpan={6} className="border border-gray-200 px-3 py-4 text-center text-gray-500">
                  No teachers yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
