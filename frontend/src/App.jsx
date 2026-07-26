import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import TimetableGridPage from './pages/TimetableGridPage'

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
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
