import { useCallback, useEffect, useRef, useState } from 'react'
import { getSolverRun } from '../api/client'

const POLL_INTERVAL_MS = 2000

// SolverRun.status values (backend/core/models.py) -- SUCCESS/FAILED are
// the only terminal ones; PENDING/RUNNING mean "keep polling".

// Shared by every "trigger an action, get back a SolverRun id, poll
// GET /api/solver-runs/<id>/ every ~2s until SUCCESS/FAILED" flow --
// first built inline in TimetableGridPage for Generate Timetable (Phase
// 5d), extracted here for Phase 7's resignation recovery so the same
// polling logic isn't duplicated a second time.
//
// trigger(triggerFn, { onSuccess }) calls triggerFn() (expected to POST
// and resolve to a {id, status} SolverRun), then polls until terminal.
// onSuccess(run) fires once, with the final SUCCESS run, for the caller to
// react to (e.g. refetch a grid). reset() clears all state and, being
// called from an effect keyed on the caller's own dependencies (e.g. the
// selected term), is how a caller abandons an in-flight run's UI tracking
// -- the polling effect's cleanup below still cancels the actual timer.
export function useSolverRunPolling(token) {
  const [runId, setRunId] = useState(null)
  const [runStatus, setRunStatus] = useState(null)
  const [error, setError] = useState('')
  const isPolling = runStatus === 'PENDING' || runStatus === 'RUNNING'

  const onSuccessRef = useRef(null)

  const trigger = useCallback(async (triggerFn, { onSuccess } = {}) => {
    setError('')
    setRunStatus('PENDING')
    onSuccessRef.current = onSuccess ?? null
    try {
      const run = await triggerFn()
      setRunId(run.id)
      setRunStatus(run.status)
    } catch (err) {
      setRunStatus('FAILED')
      setError(err.message)
    }
  }, [])

  const reset = useCallback(() => {
    setRunId(null)
    setRunStatus(null)
    setError('')
  }, [])

  // Recursive setTimeout (not setInterval) so a poll never overlaps the
  // next one, and cleanup only has one timer to worry about.
  useEffect(() => {
    if (!runId) return
    let cancelled = false
    let timeoutId = null

    async function poll() {
      try {
        const run = await getSolverRun(token, runId)
        if (cancelled) return
        setRunStatus(run.status)

        if (run.status === 'SUCCESS') {
          onSuccessRef.current?.(run)
          return
        }
        if (run.status === 'FAILED') {
          setError(run.error_message || 'The operation failed for an unknown reason.')
          return
        }
        timeoutId = setTimeout(poll, POLL_INTERVAL_MS)
      } catch (err) {
        if (!cancelled) {
          setRunStatus('FAILED')
          setError(err.message)
        }
      }
    }

    poll()

    return () => {
      cancelled = true
      if (timeoutId) clearTimeout(timeoutId)
    }
  }, [token, runId])

  return { runId, status: runStatus, error, isPolling, trigger, reset }
}
