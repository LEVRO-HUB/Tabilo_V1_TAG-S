import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { getSolverWeightConfig, updateSolverWeightConfig } from '../api/client'

const SUCCESS_MESSAGE_DURATION_MS = 4000

const WEIGHT_FIELDS = [
  {
    key: 'gap_weight',
    label: 'Gap Minimization',
    description:
      "Reduces idle gaps in a teacher's day -- clusters their free periods together instead of scattering them between teaching periods.",
  },
  {
    key: 'cognitive_load_weight',
    label: 'Cognitive Load Placement',
    description:
      'Places demanding (high cognitive-load) subjects earlier in the day, when students are fresher, rather than in the afternoon.',
  },
  {
    key: 'fair_rotation_weight',
    label: 'Fair Afternoon Rotation',
    description:
      'Balances which teachers get stuck with afternoon slots, instead of the same few teachers covering most of them.',
  },
]

export default function SolverSettingsPage() {
  const { token } = useAuth()

  const [weights, setWeights] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setLoadError('')
      try {
        const data = await getSolverWeightConfig(token)
        if (!cancelled) setWeights(data)
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
  }, [token])

  useEffect(() => {
    if (!saved) return
    const timeoutId = setTimeout(() => setSaved(false), SUCCESS_MESSAGE_DURATION_MS)
    return () => clearTimeout(timeoutId)
  }, [saved])

  function handleChange(key, value) {
    setSaved(false)
    setWeights((prev) => ({ ...prev, [key]: Number(value) }))
  }

  async function handleSave() {
    setSaving(true)
    setSaveError('')
    try {
      const data = await updateSolverWeightConfig(token, weights)
      setWeights(data)
      setSaved(true)
    } catch (err) {
      setSaveError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <p className="text-gray-500">Loading…</p>
  if (loadError) return <p className="text-red-600">{loadError}</p>

  return (
    <div className="max-w-2xl">
      <h1 className="mb-1 text-lg font-semibold text-gray-900">Solver Settings</h1>
      <p className="mb-6 text-sm text-gray-500">
        These weights shape how "Generate Timetable" picks among equally valid schedules -- higher
        means the solver works harder to avoid that particular problem, relative to the other two.
      </p>

      <div className="space-y-6 rounded-lg border border-gray-200 bg-white p-6">
        {WEIGHT_FIELDS.map(({ key, label, description }) => (
          <div key={key}>
            <div className="mb-1 flex items-center justify-between">
              <label htmlFor={key} className="text-sm font-medium text-gray-900">
                {label}
              </label>
              <span className="w-8 text-right text-sm text-gray-500">{weights[key]}</span>
            </div>
            <input
              id={key}
              type="range"
              min="0"
              max="100"
              value={weights[key]}
              onChange={(event) => handleChange(key, event.target.value)}
              className="w-full"
            />
            <p className="mt-1 text-xs text-gray-500">{description}</p>
          </div>
        ))}

        {saveError && (
          <p role="alert" className="text-sm text-red-600">
            {saveError}
          </p>
        )}
        {saved && <p className="text-sm text-green-700">Settings saved.</p>}

        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="rounded-md bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  )
}
