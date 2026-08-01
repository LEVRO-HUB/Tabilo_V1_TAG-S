import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import {
  createCourseRequirement,
  deleteCourseRequirement,
  getClassDivisions,
  getCourseRequirements,
  getSubjects,
  getTeachers,
  getTerms,
  updateCourseRequirement,
} from '../api/client'

const NO_TEACHER = '' // "Let the solver choose" -- maps to teacher: null

const EMPTY_FORM = {
  term: '', class_division: '', subject: '', teacher: NO_TEACHER,
  periods_per_week: '', is_lab: false, block_size: '1', elective_group: '',
}

export default function CourseRequirementsPage() {
  const { token } = useAuth()

  const [courseRequirements, setCourseRequirements] = useState([])
  const [terms, setTerms] = useState([])
  const [classDivisions, setClassDivisions] = useState([])
  const [subjects, setSubjects] = useState([])
  const [teachers, setTeachers] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)

  const activeTeachers = teachers.filter((teacher) => teacher.is_active)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setLoadError('')
      try {
        const [courseRequirementsData, termsData, classDivisionsData, subjectsData, teachersData] = await Promise.all([
          getCourseRequirements(token),
          getTerms(token),
          getClassDivisions(token),
          getSubjects(token),
          getTeachers(token),
        ])
        if (cancelled) return
        setCourseRequirements(courseRequirementsData)
        setTerms(termsData)
        setClassDivisions(classDivisionsData)
        setSubjects(subjectsData)
        setTeachers(teachersData)
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

  function defaultFormFor(termsData, classDivisionsData, subjectsData) {
    return {
      ...EMPTY_FORM,
      term: String((termsData.find((t) => t.is_active) ?? termsData[0])?.id ?? ''),
      class_division: String(classDivisionsData[0]?.id ?? ''),
      subject: String(subjectsData[0]?.id ?? ''),
    }
  }

  function openCreateForm() {
    setEditingId(null)
    setForm(defaultFormFor(terms, classDivisions, subjects))
    setFormError('')
    setShowForm(true)
  }

  function openEditForm(courseRequirement) {
    setEditingId(courseRequirement.id)
    setForm({
      term: String(courseRequirement.term),
      class_division: String(courseRequirement.class_division),
      subject: String(courseRequirement.subject),
      teacher: courseRequirement.teacher ? String(courseRequirement.teacher) : NO_TEACHER,
      periods_per_week: String(courseRequirement.periods_per_week),
      is_lab: courseRequirement.is_lab,
      block_size: String(courseRequirement.block_size),
      elective_group: courseRequirement.elective_group ? String(courseRequirement.elective_group) : '',
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
      term: Number(form.term),
      class_division: Number(form.class_division),
      subject: Number(form.subject),
      teacher: form.teacher ? Number(form.teacher) : null,
      periods_per_week: Number(form.periods_per_week),
      is_lab: form.is_lab,
      block_size: Number(form.block_size || 1),
      elective_group: form.elective_group ? Number(form.elective_group) : null,
    }
    try {
      if (editingId) {
        await updateCourseRequirement(token, editingId, payload)
      } else {
        await createCourseRequirement(token, payload)
      }
      closeForm()
      setRefreshKey((key) => key + 1)
    } catch (err) {
      setFormError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(courseRequirement) {
    if (!window.confirm(`Delete the ${courseRequirement.subject_name} requirement for ${courseRequirement.class_division_name}?`)) {
      return
    }
    try {
      await deleteCourseRequirement(token, courseRequirement.id)
      setRefreshKey((key) => key + 1)
    } catch (err) {
      window.alert(err.message)
    }
  }

  const canAdd = terms.length > 0 && classDivisions.length > 0 && subjects.length > 0

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900">Course Requirements</h1>
        {!showForm && (
          <button
            type="button"
            onClick={openCreateForm}
            disabled={!canAdd}
            className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            + Add Course Requirement
          </button>
        )}
      </div>

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="mb-6 space-y-4 rounded-lg border border-gray-200 bg-white p-4"
        >
          <h2 className="text-sm font-medium text-gray-900">
            {editingId ? 'Edit course requirement' : 'New course requirement'}
          </h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="cr-term" className="mb-1 block text-xs font-medium text-gray-500">Term</label>
              <select
                id="cr-term"
                required
                value={form.term}
                onChange={(event) => setForm({ ...form, term: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                {terms.map((term) => (
                  <option key={term.id} value={term.id}>{term.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="cr-class-division" className="mb-1 block text-xs font-medium text-gray-500">Class</label>
              <select
                id="cr-class-division"
                required
                value={form.class_division}
                onChange={(event) => setForm({ ...form, class_division: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                {classDivisions.map((division) => (
                  <option key={division.id} value={division.id}>{division.name} - {division.section}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="cr-subject" className="mb-1 block text-xs font-medium text-gray-500">Subject</label>
              <select
                id="cr-subject"
                required
                value={form.subject}
                onChange={(event) => setForm({ ...form, subject: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                {subjects.map((subject) => (
                  <option key={subject.id} value={subject.id}>{subject.name} ({subject.code})</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="cr-teacher" className="mb-1 block text-xs font-medium text-gray-500">Teacher</label>
              <select
                id="cr-teacher"
                value={form.teacher}
                onChange={(event) => setForm({ ...form, teacher: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                <option value={NO_TEACHER}>Let the solver choose</option>
                {activeTeachers.map((teacher) => (
                  <option key={teacher.id} value={teacher.id}>{teacher.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="cr-periods" className="mb-1 block text-xs font-medium text-gray-500">
                Periods / week
              </label>
              <input
                id="cr-periods"
                type="number"
                min="1"
                required
                value={form.periods_per_week}
                onChange={(event) => setForm({ ...form, periods_per_week: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="cr-elective-group" className="mb-1 block text-xs font-medium text-gray-500">
                Elective group ID (optional)
              </label>
              <input
                id="cr-elective-group"
                type="number"
                min="1"
                value={form.elective_group}
                onChange={(event) => setForm({ ...form, elective_group: event.target.value })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div className="flex items-center gap-2">
              <input
                id="cr-is-lab"
                type="checkbox"
                checked={form.is_lab}
                onChange={(event) => setForm({ ...form, is_lab: event.target.checked })}
                className="h-4 w-4 rounded border-gray-300"
              />
              <label htmlFor="cr-is-lab" className="text-sm text-gray-700">Lab (contiguous blocks)</label>
            </div>
            {form.is_lab && (
              <div>
                <label htmlFor="cr-block-size" className="mb-1 block text-xs font-medium text-gray-500">
                  Block size
                </label>
                <input
                  id="cr-block-size"
                  type="number"
                  min="1"
                  value={form.block_size}
                  onChange={(event) => setForm({ ...form, block_size: event.target.value })}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
            )}
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
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Term</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Class</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Subject</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Teacher</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Periods/Week</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Lab</th>
              <th className="border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
            </tr>
          </thead>
          <tbody>
            {courseRequirements.map((courseRequirement) => (
              <tr key={courseRequirement.id}>
                <td className="border border-gray-200 px-3 py-2">{courseRequirement.term_name}</td>
                <td className="border border-gray-200 px-3 py-2">{courseRequirement.class_division_name}</td>
                <td className="border border-gray-200 px-3 py-2">{courseRequirement.subject_name}</td>
                <td className="border border-gray-200 px-3 py-2">
                  {courseRequirement.teacher_name ?? <span className="italic text-gray-400">Solver's choice</span>}
                </td>
                <td className="border border-gray-200 px-3 py-2">{courseRequirement.periods_per_week}</td>
                <td className="border border-gray-200 px-3 py-2">
                  {courseRequirement.is_lab ? `Yes (block ${courseRequirement.block_size})` : 'No'}
                </td>
                <td className="border border-gray-200 px-3 py-2">
                  <div className="flex gap-3">
                    <button
                      type="button"
                      onClick={() => openEditForm(courseRequirement)}
                      className="text-purple-600 hover:underline"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(courseRequirement)}
                      className="text-red-600 hover:underline"
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {courseRequirements.length === 0 && (
              <tr>
                <td colSpan={7} className="border border-gray-200 px-3 py-4 text-center text-gray-500">
                  No course requirements yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
