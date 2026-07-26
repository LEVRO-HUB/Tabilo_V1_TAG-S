// Tabilo — thin fetch wrapper around the Django REST API (Phase 5c).
//
// Every function here either returns parsed JSON or throws an Error with a
// real, human-readable message -- callers (pages) can just show err.message
// directly, never a raw stack trace or "undefined".

const BASE_URL = import.meta.env.VITE_API_BASE_URL

async function request(path, { method = 'GET', token, body } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Token ${token}`

  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    throw new Error(await extractErrorMessage(response))
  }

  return response.json()
}

async function extractErrorMessage(response) {
  let data
  try {
    data = await response.json()
  } catch {
    return `Request failed (${response.status})`
  }

  // DRF's two common shapes: {"detail": "..."} for permission/404/explicit
  // errors, and {"non_field_errors": ["..."]} for serializer-level
  // validation errors (e.g. login with bad credentials).
  if (data?.detail) return data.detail
  if (Array.isArray(data?.non_field_errors) && data.non_field_errors.length > 0) {
    return data.non_field_errors[0]
  }
  return `Request failed (${response.status})`
}

export function login(username, password) {
  return request('/api/auth/login/', { method: 'POST', body: { username, password } })
}

export function getTerms(token) {
  return request('/api/terms/', { token })
}

export function getClassDivisions(token) {
  return request('/api/class-divisions/', { token })
}

export function getTimetableGrid(token, termId, classDivisionId) {
  const params = new URLSearchParams({ term_id: termId, class_division_id: classDivisionId })
  return request(`/api/timetable-grid/?${params}`, { token })
}

export function triggerSolverRun(token, termId, feasibilityOnly = false) {
  return request('/api/solver-runs/', {
    method: 'POST',
    token,
    body: { term_id: termId, feasibility_only: feasibilityOnly },
  })
}

export function getSolverRun(token, runId) {
  return request(`/api/solver-runs/${runId}/`, { token })
}
