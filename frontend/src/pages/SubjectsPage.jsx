import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { createSubject, deleteSubject, getDepartments, getSubjects, updateSubject } from '../api/client'

const EMPTY_FORM = { name: '', code: '', department: '', is_elective: false, cognitive_load_priority: 'NORMAL' }

export default function SubjectsPage() {
  const { token } = useAuth()

  const [subjects, setSubjects] = useState([])
  const [departments, setDepartments] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setLoadError('')
      try {
        const [subjectsData, departmentsData] = await Promise.all([getSubjects(token), getDepartments(token)])
        if (cancelled) return
        setSubjects(subjectsData)
        setDepartments(departmentsData)
        setForm((prev) => (prev.department ? prev : { ...prev, department: String(departmentsData[0]?.id ?? '') }))
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

  function openCreateForm() {
    setEditingId(null)
    setForm({ ...EMPTY_FORM, department: String(departments[0]?.id ?? '') })
    setFormError('')
    setShowForm(true)
  }

  function openEditForm(subject) {
    setEditingId(subject.id)
    setForm({
      name: subject.name,
      code: subject.code,
      department: String(subject.department),
      is_elective: subject.is_elective,
      cognitive_load_priority: subject.cognitive_load_priority,
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
      code: form.code,
      department: Number(form.department),
      is_elective: form.is_elective,
      cognitive_load_priority: form.cognitive_load_priority,
    }
    try {
      if (editingId) {
        await updateSubject(token, editingId, payload)
      } else {
        await createSubject(token, payload)
      }
      closeForm()
      setRefreshKey((key) => key + 1)
    } catch (err) {
      setFormError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(subject) {
    // Subject's FKs from CourseRequirement and TimetableCell are both
    // on_delete=CASCADE (backend/core/api/views.py's SubjectDetailView) --
    // deleting a subject silently takes its course requirements and any
    // already-generated timetable cells with it, so the prompt says so.
    const confirmed = window.confirm(
      `Delete ${subject.name} (${subject.code})? This also deletes any course requirements and ` +
        'generated timetable cells for this subject. This cannot be undone.'
    )
    if (!confirmed) return
    try {
      await deleteSubject(token, subject.id)
      setRefreshKey((key) => key + 1)
    } catch (err) {
      window.alert(err.message)
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900">Subjects</h1>
        {!showForm && (
          <button
            type="button"
            onClick={openCreateForm}
            disabled={departments.length === 0}
            className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            + Add Subject
          </button>
        )}
      </div>

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="mb-6 space-y-4 rounded-lg border border-gray-200 bg-white p-4"
        >
          <h2 className="text-sm font-medium text-gray-900">{editingId ? 'Edit subject' : 'New subject'}</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="subject-name" className="mb-1 block text-xs font-medium text-gray-500">Name</label>
              <input
                id="subject-name"
                type="text"
                required
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="subject-code" className="mb-1 block text-xs font-medium text-gray-500">Code</label>
              <input
                id="subject-code"
                type="text"
                required
                value={form.code}
                onChange={(event) => setForm({ ...form, code: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="subject-department" className="mb-1 block text-xs font-medium text-gray-500">
                Department
              </label>
              <select
                id="subject-department"
                required
                value={form.department}
                onChange={(event) => setForm({ ...form, department: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                {departments.map((department) => (
                  <option key={department.id} value={department.id}>{department.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="subject-cognitive-load" className="mb-1 block text-xs font-medium text-gray-500">
                Cognitive load priority
              </label>
              <select
                id="subject-cognitive-load"
                value={form.cognitive_load_priority}
                onChange={(event) => setForm({ ...form, cognitive_load_priority: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="NORMAL">Normal</option>
                <option value="HIGH">High</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <input
                id="subject-elective"
                type="checkbox"
                checked={form.is_elective}
                onChange={(event) => setForm({ ...form, is_elective: event.target.checked })}
                className="h-4 w-4 rounded border-gray-300"
              />
              <label htmlFor="subject-elective" className="text-sm text-gray-700">Elective</label>
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
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Code</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Department</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Elective</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Cognitive Load</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
            </tr>
          </thead>
          <tbody>
            {subjects.map((subject) => (
              <tr key={subject.id}>
                <td className="border border-gray-200 px-3 py-2">{subject.name}</td>
                <td className="border border-gray-200 px-3 py-2">{subject.code}</td>
                <td className="border border-gray-200 px-3 py-2">{subject.department_name}</td>
                <td className="border border-gray-200 px-3 py-2">{subject.is_elective ? 'Yes' : 'No'}</td>
                <td className="border border-gray-200 px-3 py-2">{subject.cognitive_load_priority}</td>
                <td className="border border-gray-200 px-3 py-2">
                  <div className="flex gap-3">
                    <button
                      type="button"
                      onClick={() => openEditForm(subject)}
                      className="text-purple-600 hover:underline"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(subject)}
                      className="text-red-600 hover:underline"
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {subjects.length === 0 && (
              <tr>
                <td colSpan={6} className="border border-gray-200 px-3 py-4 text-center text-gray-500">
                  No subjects yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
