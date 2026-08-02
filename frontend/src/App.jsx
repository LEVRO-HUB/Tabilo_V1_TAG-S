import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import TimetableGridPage from './pages/TimetableGridPage'
import TeachersPage from './pages/TeachersPage'
import SubjectsPage from './pages/SubjectsPage'
import CourseRequirementsPage from './pages/CourseRequirementsPage'
import TodaysSchedulePage from './pages/TodaysSchedulePage'

const MANAGEMENT_ROLES = ['ADMIN', 'COORDINATOR']

function LoginRoute() {
  const { token } = useAuth()
  if (token) return <Navigate to="/" replace />
  return <LoginPage />
}

function ProtectedRoute({ children }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return children
}

// A hidden nav link is UI tidiness, not access control -- a TEACHER-role
// user who navigates straight to /teachers (bookmark, typed URL) must still
// be blocked here, at the route level, not just kept from seeing the link.
function ManagementRoute({ children }) {
  const { user } = useAuth()
  if (!MANAGEMENT_ROLES.includes(user?.role)) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        You don't have access to this page.
      </div>
    )
  }
  return children
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginRoute />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Layout>
                  <TimetableGridPage />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/teachers"
            element={
              <ProtectedRoute>
                <Layout>
                  <ManagementRoute>
                    <TeachersPage />
                  </ManagementRoute>
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/subjects"
            element={
              <ProtectedRoute>
                <Layout>
                  <ManagementRoute>
                    <SubjectsPage />
                  </ManagementRoute>
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/course-requirements"
            element={
              <ProtectedRoute>
                <Layout>
                  <ManagementRoute>
                    <CourseRequirementsPage />
                  </ManagementRoute>
                </Layout>
              </ProtectedRoute>
            }
          />
          {/* Deliberately NOT wrapped in ManagementRoute -- the backend's
              TodaysScheduleView is intentionally open to every authenticated
              role (see its docstring): "who's covering what today" is
              useful to a TEACHER too, same as the timetable grid. Only the
              nav link is ADMIN/COORDINATOR-only (Layout.jsx); the page
              itself hides the "Find substitute" action (a management
              action) from non-managers rather than blocking the whole page. */}
          <Route
            path="/todays-schedule"
            element={
              <ProtectedRoute>
                <Layout>
                  <TodaysSchedulePage />
                </Layout>
              </ProtectedRoute>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
