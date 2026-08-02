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

  if (response.status === 204) return null // DELETE -- no body to parse
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

export function getDepartments(token) {
  return request('/api/departments/', { token })
}

export function getTeachers(token) {
  return request('/api/teachers/', { token })
}

export function createTeacher(token, teacher) {
  return request('/api/teachers/', { method: 'POST', token, body: teacher })
}

export function updateTeacher(token, teacherId, patch) {
  return request(`/api/teachers/${teacherId}/`, { method: 'PATCH', token, body: patch })
}

export function getSubjects(token) {
  return request('/api/subjects/', { token })
}

export function createSubject(token, subject) {
  return request('/api/subjects/', { method: 'POST', token, body: subject })
}

export function updateSubject(token, subjectId, patch) {
  return request(`/api/subjects/${subjectId}/`, { method: 'PATCH', token, body: patch })
}

export function deleteSubject(token, subjectId) {
  return request(`/api/subjects/${subjectId}/`, { method: 'DELETE', token })
}

export function getCourseRequirements(token) {
  return request('/api/course-requirements/', { token })
}

export function createCourseRequirement(token, courseRequirement) {
  return request('/api/course-requirements/', { method: 'POST', token, body: courseRequirement })
}

export function updateCourseRequirement(token, courseRequirementId, patch) {
  return request(`/api/course-requirements/${courseRequirementId}/`, { method: 'PATCH', token, body: patch })
}

export function deleteCourseRequirement(token, courseRequirementId) {
  return request(`/api/course-requirements/${courseRequirementId}/`, { method: 'DELETE', token })
}

export function triggerResignationRecovery(token, teacherId, termId) {
  return request('/api/resignation-recovery/', {
    method: 'POST',
    token,
    body: { teacher_id: teacherId, term_id: termId },
  })
}

export function getTodaysSchedule(token, date) {
  const params = date ? `?${new URLSearchParams({ date })}` : ''
  return request(`/api/todays-schedule/${params}`, { token })
}

export function getSubstitutionSuggestions(token, cellId, date) {
  const params = new URLSearchParams({ cell_id: cellId, date })
  return request(`/api/substitution-suggestions/?${params}`, { token })
}

export function createSubstitution(token, cellId, date, substituteTeacherId, reason = '') {
  return request('/api/substitutions/', {
    method: 'POST',
    token,
    body: { cell_id: cellId, date, substitute_teacher_id: substituteTeacherId, reason },
  })
}
